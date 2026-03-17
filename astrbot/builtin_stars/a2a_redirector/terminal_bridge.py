from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import os
import pty
import re
import select
import shlex
import shutil
import termios
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

PROMPT_MARKER = "__ASTRBOT_PROMPT__> "


class TerminalBridgeError(RuntimeError):
    pass


@dataclass(slots=True)
class TerminalCommandResult:
    output: str
    cwd: str
    exit_code: int


def resolve_local_executable(executable: str) -> str:
    resolved_executable = shutil.which(executable)
    if resolved_executable is not None:
        return resolved_executable

    candidate = Path(executable).expanduser()
    if candidate.exists():
        return str(candidate.resolve())

    raise TerminalBridgeError(f"Shell executable not found: {executable}")


def resolve_working_directory(working_directory: str | None) -> str:
    if working_directory:
        candidate = Path(working_directory)
        if candidate.exists():
            return str(candidate.resolve())
    return str(Path.cwd())


def build_terminal_command(shell_name: str, command: str, marker: str) -> str:
    start_marker = f"{marker}:BEGIN"
    del shell_name
    return (
        f"printf '\\n{start_marker}\\n'\n"
        f"{command}\n"
        f'printf \'\\n{marker}:%s:%s\\n\' "$?" "$PWD"\n'
    )


def build_fish_terminal_command(command: str, marker: str) -> str:
    start_marker = f"{marker}:BEGIN"
    return (
        f"printf '\\n{start_marker}\\n'\n"
        f"{command}\n"
        f"printf '\\n{marker}:%s:%s\\n' $status (pwd)\n"
    )


def build_terminal_source_command(shell_name: str, script_path: Path) -> str:
    quoted_path = shlex.quote(str(script_path))
    if shell_name == "fish":
        return f"source {quoted_path}\n"
    return f". {quoted_path}\n"


def parse_terminal_output(payload: str, marker: str) -> TerminalCommandResult:
    start_marker = f"{marker}:BEGIN"
    match = re.search(
        rf"{re.escape(marker)}:(-?\d+):(.*?)(?:\r?\n|$)",
        payload,
        flags=re.DOTALL,
    )
    if not match:
        raise TerminalBridgeError(
            "Terminal command finished without a completion marker."
        )

    start_match = re.search(
        rf"(?:^|\r?\n){re.escape(start_marker)}(?:\r?\n|$)",
        payload,
        flags=re.DOTALL,
    )
    output_start = start_match.end() if start_match else 0
    output = payload[output_start : match.start()]
    output = output.replace(PROMPT_MARKER, "")
    output = output.strip("\r\n")
    exit_code = int(match.group(1))
    cwd = match.group(2).strip() or str(Path.cwd())
    return TerminalCommandResult(output=output, cwd=cwd, exit_code=exit_code)


def _is_pty_eof_error(exc: OSError) -> bool:
    return exc.errno == errno.EIO


def _make_controlling_tty(slave_fd: int):
    def _preexec() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    return _preexec


class TerminalSession:
    def __init__(
        self,
        *,
        executable: str,
        working_directory: str | None,
    ) -> None:
        self.executable = executable
        self.working_directory = (
            str(Path(working_directory).resolve())
            if working_directory
            else str(Path.cwd())
        )
        self.process: asyncio.subprocess.Process | None = None
        self.master_fd: int | None = None
        self._lock = asyncio.Lock()

    @property
    def shell_name(self) -> str:
        return Path(self.executable).name

    @classmethod
    async def create(
        cls,
        *,
        executable: str,
        working_directory: str | None,
    ) -> TerminalSession:
        session = cls(executable=executable, working_directory=working_directory)
        await session._start()
        return session

    async def execute(
        self,
        command: str,
        *,
        timeout_seconds: int,
    ) -> TerminalCommandResult:
        async with self._lock:
            if (
                not self.process
                or self.process.returncode is not None
                or self.master_fd is None
            ):
                raise TerminalBridgeError("The terminal session is not running.")

            self._drain_pending_output()
            marker = f"__ASTRBOT_DONE_{uuid4().hex}__"
            script_path = self._write_command_script(command, marker)
            payload = build_terminal_source_command(self.shell_name, script_path)
            try:
                os.write(self.master_fd, payload.encode("utf-8", errors="ignore"))
                response = await asyncio.to_thread(
                    self._read_until_marker,
                    marker,
                    timeout_seconds,
                )
            finally:
                with contextlib.suppress(OSError):
                    script_path.unlink()
            result = parse_terminal_output(response, marker)
            self.working_directory = result.cwd
            return result

    async def close(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.process.wait(), timeout=2)
            if self.process.returncode is None:
                self.process.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.process.wait(), timeout=2)

        if self.master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.master_fd)
            self.master_fd = None

    async def _start(self) -> None:
        resolved_executable = resolve_local_executable(self.executable)
        self.working_directory = resolve_working_directory(self.working_directory)

        master_fd, slave_fd = pty.openpty()
        os.set_blocking(master_fd, False)

        try:
            self.process = await asyncio.create_subprocess_exec(
                resolved_executable,
                "-i",
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.working_directory,
                env={
                    **os.environ,
                    "TERM": "dumb",
                    "COLUMNS": "120",
                    "LINES": "40",
                },
                preexec_fn=_make_controlling_tty(slave_fd),
            )
        finally:
            with contextlib.suppress(OSError):
                os.close(slave_fd)

        self.master_fd = master_fd
        self.executable = resolved_executable
        await asyncio.sleep(0.2)
        self._drain_pending_output()
        init_script = self._build_init_script()
        if init_script:
            os.write(master_fd, init_script.encode("utf-8", errors="ignore"))
            await asyncio.sleep(0.1)
            self._drain_pending_output()

    def _build_init_script(self) -> str:
        if self.shell_name == "fish":
            return (
                "function fish_prompt\n"
                f"    printf '{PROMPT_MARKER}'\n"
                "end\n"
                "function fish_right_prompt\n"
                "end\n"
                "stty -echo\n"
            )
        return (
            f"export PS1='{PROMPT_MARKER}'\n"
            f"export PROMPT='{PROMPT_MARKER}'\n"
            "stty -echo\n"
        )

    def _write_command_script(self, command: str, marker: str) -> Path:
        temp_dir = Path(get_astrbot_temp_path()) / "a2a_redirector"
        temp_dir.mkdir(parents=True, exist_ok=True)

        if self.shell_name == "fish":
            script_content = build_fish_terminal_command(command, marker)
            suffix = ".fish"
        else:
            script_content = build_terminal_command(self.shell_name, command, marker)
            suffix = ".sh"

        script_path = temp_dir / f"terminal_command_{uuid4().hex}{suffix}"
        script_path.write_text(script_content, encoding="utf-8")
        return script_path

    def _drain_pending_output(self) -> str:
        if self.master_fd is None:
            return ""
        chunks: list[str] = []
        while True:
            ready, _, _ = select.select([self.master_fd], [], [], 0.05)
            if not ready:
                break
            try:
                data = os.read(self.master_fd, 4096)
            except BlockingIOError:
                break
            except OSError as exc:
                if _is_pty_eof_error(exc):
                    break
                raise
            if not data:
                break
            chunks.append(data.decode("utf-8", errors="ignore"))
        return "".join(chunks)

    def _read_until_marker(self, marker: str, timeout_seconds: int) -> str:
        if self.master_fd is None:
            raise TerminalBridgeError("The terminal PTY is not available.")

        deadline = time.monotonic() + max(timeout_seconds, 1)
        chunks: list[str] = []
        pattern = re.compile(
            rf"{re.escape(marker)}:(-?\d+):(.*?)(?:\r?\n|$)",
            re.DOTALL,
        )

        while True:
            if self.process and self.process.returncode is not None:
                break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TerminalBridgeError(
                    "Timed out while waiting for terminal output."
                )

            ready, _, _ = select.select([self.master_fd], [], [], min(remaining, 0.2))
            if not ready:
                continue

            try:
                data = os.read(self.master_fd, 4096)
            except BlockingIOError:
                continue
            except OSError as exc:
                if _is_pty_eof_error(exc):
                    break
                raise

            if not data:
                break

            chunks.append(data.decode("utf-8", errors="ignore"))
            payload = "".join(chunks)
            if pattern.search(payload):
                return payload

        payload = "".join(chunks)
        if payload:
            logger.debug(
                "[A2A Redirector] Terminal session ended with trailing output: %s",
                payload,
            )
        raise TerminalBridgeError(
            "Terminal session ended before the command completed."
        )


class TerminalSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        session_key: str,
        *,
        executable: str,
        command: str,
        working_directory: str | None,
        timeout_seconds: int,
    ) -> TerminalCommandResult:
        session = await self._get_or_create_session(
            session_key=session_key,
            executable=executable,
            working_directory=working_directory,
        )
        return await session.execute(command, timeout_seconds=timeout_seconds)

    async def close_session(self, session_key: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_key, None)
        if session:
            await session.close()

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.close()

    async def _get_or_create_session(
        self,
        *,
        session_key: str,
        executable: str,
        working_directory: str | None,
    ) -> TerminalSession:
        async with self._lock:
            session = self._sessions.get(session_key)
            if session and (
                session.process is None
                or session.process.returncode is not None
                or session.executable != executable
            ):
                await session.close()
                self._sessions.pop(session_key, None)
                session = None

            if session is None:
                session = await TerminalSession.create(
                    executable=executable,
                    working_directory=working_directory,
                )
                self._sessions[session_key] = session
            return session
