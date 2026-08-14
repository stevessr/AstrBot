import asyncio
import os
import shutil
import zipfile
from pathlib import Path

from astrbot.core.repository import GitUnavailableError, is_git_available
from astrbot.core.utils.io import ensure_dir, remove_dir

__all__ = ["REPOSITORY_GIT_CLONE_TIMEOUT_SECONDS", "_GitRepoUpdater"]

REPOSITORY_GIT_CLONE_TIMEOUT_SECONDS = 180


class _GitRepoUpdater:
    """Provide Git-based repository checkout helpers for updaters."""

    @staticmethod
    def is_git_available() -> bool:
        return is_git_available()

    async def _clone_repository(
        self,
        repo_url: str,
        target_path: str | Path,
        *,
        branch: str | None = None,
        require_git: bool = False,
        timeout: float = REPOSITORY_GIT_CLONE_TIMEOUT_SECONDS,
    ) -> None:
        """Shallow-clone a remote Git repository without retaining Git metadata."""
        git_executable = shutil.which("git")
        if not git_executable:
            if require_git:
                raise GitUnavailableError(
                    "安装此仓库需要 Git，但当前运行环境中未找到 git 命令。"
                )
            raise RuntimeError("Git is not available")

        target = Path(target_path)
        if target.exists():
            raise RuntimeError(f"Git clone target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        process_env = os.environ.copy()
        process_env["GIT_TERMINAL_PROMPT"] = "0"
        clone_args = [
            git_executable,
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--no-tags",
        ]
        if branch:
            clone_args.extend(["--branch", branch])
        clone_args.extend(["--", repo_url, str(target)])
        process = await asyncio.create_subprocess_exec(
            *clone_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_env,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            if target.exists():
                remove_dir(str(target))
            raise RuntimeError("Git clone timed out.") from exc

        if process.returncode != 0:
            if target.exists():
                remove_dir(str(target))
            detail = stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise RuntimeError(f"Git clone failed: {detail or 'unknown error'}")

        git_metadata = target / ".git"
        if git_metadata.exists():
            remove_dir(str(git_metadata))

    @staticmethod
    def _archive_directory(source_dir: Path, zip_path: Path, root_name: str) -> None:
        ensure_dir(zip_path.parent)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in source_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                archive.write(
                    file_path,
                    Path(root_name) / file_path.relative_to(source_dir),
                )
