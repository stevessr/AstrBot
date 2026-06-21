from __future__ import annotations

import asyncio
import html
import os
import re
import shutil
import ssl
import tempfile
import traceback
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
import certifi

from astrbot.core import DEMO_MODE, logger
from astrbot.core.computer.computer_client import (
    _discover_bay_credentials,
    sync_skills_to_active_sandboxes,
)
from astrbot.core.skills.neo_skill_sync import NeoSkillSyncManager
from astrbot.core.skills.skill_manager import SkillManager
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

_GITHUB_SOURCE_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$"
)
_SKILLS_SH_HOSTS = {"skills.sh", "www.skills.sh"}
_SKILLS_SH_BASE_URL = "https://www.skills.sh"
_SKILLS_SH_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>/[^"]+)"[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SKILLS_SH_INSTALL_RE = re.compile(
    r"npx\s+skills\s+add\s+(?P<target>\S+)"
    r"(?:\s+--skill\s+(?P<skill>[A-Za-z0-9._-]+))?",
    re.IGNORECASE,
)
_SKILL_FOLDER_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _parse_frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        line_key, value = line.split(":", 1)
        if line_key.strip().lower() == key.lower():
            return value.strip().strip('"').strip("'")
    return ""


_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SKILL_FILE_MAX_BYTES = 512 * 1024
_EDITABLE_SKILL_FILE_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
_EDITABLE_SKILL_FILENAMES = {"Dockerfile", "Makefile"}


class SkillsServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class SkillsOperationResult:
    ok: bool = True
    data: dict | list | None = None
    message: str | None = None


@dataclass
class SkillArchive:
    path: Path
    filename: str


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    return value


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _next_available_temp_path(temp_dir: str, filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    index = 1
    while os.path.exists(os.path.join(temp_dir, candidate)):
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    return os.path.join(temp_dir, candidate)


class SkillsService:
    def __init__(self, core_lifecycle) -> None:
        self.core_lifecycle = core_lifecycle

    @staticmethod
    def _payload(data: object) -> dict[str, Any]:
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _ensure_mutation_allowed() -> None:
        if DEMO_MODE:
            raise SkillsServiceError(
                "You are not permitted to do this operation in demo mode"
            )

    @staticmethod
    async def _save_upload(file: Any, target_path: str) -> None:
        if hasattr(file, "save"):
            maybe_awaitable = file.save(target_path)
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable
            return

        if hasattr(file, "read"):
            data = file.read()
            if hasattr(data, "__await__"):
                data = await data
            Path(target_path).write_bytes(data)
            return

        raise SkillsServiceError("Invalid upload file")

    def resolve_local_skill_dir(self, name: str) -> Path:
        skill_name = str(name or "").strip()
        if not skill_name:
            raise ValueError("Missing skill name")
        if not _SKILL_NAME_RE.match(skill_name):
            raise ValueError("Invalid skill name")

        skill_mgr = SkillManager()
        if skill_mgr.is_sandbox_only_skill(skill_name):
            raise PermissionError(
                "Sandbox preset skill cannot be opened from local skill files."
            )

        plugin_skill_dir = skill_mgr._get_plugin_skill_dir(skill_name)
        if plugin_skill_dir is not None:
            return plugin_skill_dir.resolve(strict=True)

        skills_root = Path(skill_mgr.skills_root).resolve(strict=True)
        skill_dir = (skills_root / skill_name).resolve(strict=True)
        if not skill_dir.is_relative_to(skills_root):
            raise PermissionError("Invalid skill path")
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            raise FileNotFoundError("Local skill not found")
        return skill_dir

    @staticmethod
    def resolve_skill_relative_path(
        skill_dir: Path,
        relative_path: str | None,
        *,
        expect_file: bool,
    ) -> Path:
        raw_path = str(relative_path or ".").strip() or "."
        normalized = Path(raw_path.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Invalid relative path")

        target = (skill_dir / normalized).resolve(strict=True)
        if not target.is_relative_to(skill_dir):
            raise PermissionError("Path escapes skill directory")
        if expect_file and not target.is_file():
            raise FileNotFoundError("Skill file not found")
        if not expect_file and not target.is_dir():
            raise FileNotFoundError("Skill directory not found")
        return target

    @staticmethod
    def skill_relative_path(skill_dir: Path, target: Path) -> str:
        rel = target.relative_to(skill_dir).as_posix()
        return "" if rel == "." else rel

    @staticmethod
    def is_editable_skill_file(path: Path) -> bool:
        return (
            path.name in _EDITABLE_SKILL_FILENAMES
            or path.suffix.lower() in _EDITABLE_SKILL_FILE_SUFFIXES
        )

    def serialize_skill_file_entry(
        self,
        skill_dir: Path,
        path: Path,
        *,
        readonly: bool = False,
    ) -> dict:
        stat = path.stat()
        is_dir = path.is_dir()
        return {
            "name": path.name,
            "path": self.skill_relative_path(skill_dir, path),
            "type": "directory" if is_dir else "file",
            "size": 0 if is_dir else stat.st_size,
            "editable": (
                not readonly
                and (not is_dir)
                and self.is_editable_skill_file(path)
                and stat.st_size <= _SKILL_FILE_MAX_BYTES
            ),
        }

    def get_neo_client_config(self) -> tuple[str, str]:
        provider_settings = self.core_lifecycle.astrbot_config.get(
            "provider_settings",
            {},
        )
        sandbox = provider_settings.get("sandbox", {})
        endpoint = sandbox.get("shipyard_neo_endpoint", "")
        access_token = sandbox.get("shipyard_neo_access_token", "")

        if not access_token and endpoint:
            access_token = _discover_bay_credentials(endpoint)

        if not endpoint or not access_token:
            raise ValueError(
                "Shipyard Neo endpoint or access token not configured. "
                "Set them in Dashboard or ensure Bay's credentials.json is accessible."
            )
        return endpoint, access_token

    async def with_neo_client(
        self,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> SkillsOperationResult:
        try:
            endpoint, access_token = self.get_neo_client_config()

            from shipyard_neo import BayClient

            async with BayClient(
                endpoint_url=endpoint,
                access_token=access_token,
            ) as client:
                result = await operation(client)
                if isinstance(result, SkillsOperationResult):
                    return result
                return SkillsOperationResult(data=_to_jsonable(result))
        except ValueError as exc:
            logger.debug("[Neo] %s", exc)
            return SkillsOperationResult(ok=False, message=str(exc))
        except Exception as exc:
            logger.error(traceback.format_exc())
            return SkillsOperationResult(ok=False, message=str(exc))

    def get_skills(self) -> dict:
        provider_settings = self.core_lifecycle.astrbot_config.get(
            "provider_settings", {}
        )
        runtime = provider_settings.get("computer_use_runtime", "local")
        skill_mgr = SkillManager()
        skills = skill_mgr.list_skills(
            active_only=False,
            runtime=runtime,
            show_sandbox_path=False,
        )
        return {
            "skills": [skill.__dict__ for skill in skills],
            "runtime": runtime,
            "sandbox_cache": skill_mgr.get_sandbox_skills_cache_status(),
        }

    async def upload_skill(self, file: Any | None) -> SkillsOperationResult:
        self._ensure_mutation_allowed()
        temp_path = None
        if not file:
            raise SkillsServiceError("Missing file")

        filename = os.path.basename(file.filename or "skill.zip")
        if not filename.lower().endswith(".zip"):
            raise SkillsServiceError("Only .zip files are supported")

        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)
        skill_mgr = SkillManager()
        temp_path = _next_available_temp_path(temp_dir, filename)

        try:
            await self._save_upload(file, temp_path)
            try:
                skill_name = skill_mgr.install_skill_from_zip(
                    temp_path,
                    overwrite=False,
                    skill_name_hint=Path(filename).stem,
                )
            except TypeError:
                skill_name = skill_mgr.install_skill_from_zip(
                    temp_path,
                    overwrite=False,
                )

            try:
                await sync_skills_to_active_sandboxes()
            except Exception:
                logger.warning("Failed to sync uploaded skills to active sandboxes.")

            return SkillsOperationResult(
                data={"name": skill_name},
                message="Skill uploaded successfully.",
            )
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    logger.warning(f"Failed to remove temp skill file: {temp_path}")

    async def batch_upload_skills(self, file_list: list[Any]) -> SkillsOperationResult:
        self._ensure_mutation_allowed()

        if not file_list:
            raise SkillsServiceError("No files provided")

        succeeded = []
        failed = []
        skipped = []
        skill_mgr = SkillManager()
        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)

        for file in file_list:
            filename = os.path.basename(file.filename or "unknown.zip")
            temp_path = None

            try:
                if not filename.lower().endswith(".zip"):
                    failed.append(
                        {
                            "filename": filename,
                            "error": "Only .zip files are supported",
                        }
                    )
                    continue

                temp_path = _next_available_temp_path(temp_dir, filename)
                await self._save_upload(file, temp_path)

                try:
                    skill_name = skill_mgr.install_skill_from_zip(
                        temp_path,
                        overwrite=False,
                        skill_name_hint=Path(filename).stem,
                    )
                except TypeError:
                    try:
                        skill_name = skill_mgr.install_skill_from_zip(
                            temp_path,
                            overwrite=False,
                        )
                    except FileExistsError:
                        skipped.append(
                            {
                                "filename": filename,
                                "name": Path(filename).stem,
                                "error": "Skill already exists.",
                            }
                        )
                        skill_name = None
                except FileExistsError:
                    skipped.append(
                        {
                            "filename": filename,
                            "name": Path(filename).stem,
                            "error": "Skill already exists.",
                        }
                    )
                    skill_name = None

                if skill_name is None:
                    continue
                succeeded.append({"filename": filename, "name": skill_name})

            except Exception as exc:
                failed.append({"filename": filename, "error": str(exc)})
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

        if succeeded:
            try:
                await sync_skills_to_active_sandboxes()
            except Exception:
                logger.warning("Failed to sync uploaded skills to active sandboxes.")

        total = len(file_list)
        success_count = len(succeeded)
        skipped_count = len(skipped)
        failed_count = len(failed)
        data = {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
        }

        if failed_count == 0 and success_count == total:
            return SkillsOperationResult(
                data=data,
                message=f"All {total} skill(s) uploaded successfully.",
            )
        if failed_count == 0 and success_count == 0:
            return SkillsOperationResult(
                data=data,
                message=f"All {total} file(s) were skipped.",
            )
        if success_count == 0 and skipped_count == 0:
            return SkillsOperationResult(
                ok=False,
                data=data,
                message=f"Upload failed for all {total} file(s).",
            )

        return SkillsOperationResult(
            data=data,
            message=f"Partial success: {success_count}/{total} skill(s) uploaded.",
        )

    def prepare_skill_archive(self, name: str) -> SkillArchive:
        skill_name = str(name or "").strip()
        if not skill_name:
            raise SkillsServiceError("Missing skill name")
        if not _SKILL_NAME_RE.match(skill_name):
            raise SkillsServiceError("Invalid skill name")

        skill_mgr = SkillManager()
        if skill_mgr.is_sandbox_only_skill(skill_name):
            raise SkillsServiceError(
                "Sandbox preset skill cannot be downloaded from local skill files."
            )
        if skill_mgr.is_plugin_skill(skill_name):
            raise SkillsServiceError(
                "Plugin-provided skill cannot be downloaded from local skill files."
            )

        skill_dir = Path(skill_mgr.skills_root) / skill_name
        skill_md = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_md.exists():
            raise SkillsServiceError("Local skill not found", status_code=404)

        export_dir = Path(get_astrbot_temp_path()) / "skill_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        zip_base = export_dir / skill_name
        # with_suffix(".zip") replaces only the last suffix (e.g. ".0" in
        # "skill-writing-1.0.0"), producing "skill-writing-1.0.zip" —
        # which mismatches shutil.make_archive's "skill-writing-1.0.0.zip".
        # Append ".zip" to the full name instead.
        zip_path = zip_base.with_name(zip_base.name + ".zip")
        if zip_path.exists():
            zip_path.unlink()

        shutil.make_archive(
            str(zip_base),
            "zip",
            root_dir=str(skill_mgr.skills_root),
            base_dir=skill_name,
        )
        return SkillArchive(path=zip_path, filename=f"{skill_name}.zip")

    def prepare_skill_archive_from_dashboard_query(
        self, name: str | None
    ) -> SkillArchive:
        return self.prepare_skill_archive(name or "")

    def list_skill_files(self, name: str, relative_path: str | None = "") -> dict:
        skill_name = str(name or "").strip()
        readonly = SkillManager().is_plugin_skill(skill_name)
        skill_dir = self.resolve_local_skill_dir(skill_name)
        target_dir = self.resolve_skill_relative_path(
            skill_dir,
            relative_path,
            expect_file=False,
        )

        entries = []
        for entry in sorted(
            target_dir.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        ):
            try:
                resolved = entry.resolve(strict=True)
            except OSError:
                continue
            if not resolved.is_relative_to(skill_dir):
                continue
            if not resolved.is_dir() and not resolved.is_file():
                continue
            entries.append(
                self.serialize_skill_file_entry(
                    skill_dir,
                    resolved,
                    readonly=readonly,
                )
            )

        return {
            "name": skill_name,
            "path": self.skill_relative_path(skill_dir, target_dir),
            "entries": entries,
        }

    def list_skill_files_from_dashboard_query(
        self,
        *,
        name: str | None,
        relative_path: str | None,
    ) -> dict:
        return self.list_skill_files(name or "", relative_path or "")

    def get_skill_file(self, name: str, relative_path: str | None = "SKILL.md") -> dict:
        skill_name = str(name or "").strip()
        skill_dir = self.resolve_local_skill_dir(skill_name)
        target_file = self.resolve_skill_relative_path(
            skill_dir,
            relative_path,
            expect_file=True,
        )
        if not self.is_editable_skill_file(target_file):
            raise SkillsServiceError("Unsupported file type")

        size = target_file.stat().st_size
        if size > _SKILL_FILE_MAX_BYTES:
            raise SkillsServiceError("File is too large")

        try:
            content = target_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SkillsServiceError("File is not valid UTF-8 text") from exc

        return {
            "name": skill_name,
            "path": self.skill_relative_path(skill_dir, target_file),
            "content": content,
            "size": size,
            "editable": not SkillManager().is_plugin_skill(skill_name),
        }

    def get_skill_file_from_dashboard_query(
        self,
        *,
        name: str | None,
        relative_path: str | None,
    ) -> dict:
        return self.get_skill_file(name or "", relative_path or "SKILL.md")

    async def update_skill_file(self, data: object) -> dict:
        self._ensure_mutation_allowed()
        payload = self._payload(data)
        skill_name = str(payload.get("name") or "").strip()
        relative_path = payload.get("path", "SKILL.md")
        content = payload.get("content")
        if not isinstance(content, str):
            raise SkillsServiceError("Missing file content")

        encoded = content.encode("utf-8")
        if len(encoded) > _SKILL_FILE_MAX_BYTES:
            raise SkillsServiceError("File content is too large")

        skill_dir = self.resolve_local_skill_dir(skill_name)
        if SkillManager().is_plugin_skill(skill_name):
            raise SkillsServiceError("Plugin-provided skill is read-only.")
        target_file = self.resolve_skill_relative_path(
            skill_dir,
            relative_path,
            expect_file=True,
        )
        if not self.is_editable_skill_file(target_file):
            raise SkillsServiceError("Unsupported file type")

        target_file.write_text(content, encoding="utf-8")

        try:
            await sync_skills_to_active_sandboxes()
        except Exception:
            logger.warning("Failed to sync edited skills to active sandboxes.")

        return {
            "name": skill_name,
            "path": self.skill_relative_path(skill_dir, target_file),
            "size": len(encoded),
        }

    def update_skill(self, data: object) -> dict:
        self._ensure_mutation_allowed()
        payload = self._payload(data)
        name = payload.get("name")
        active = payload.get("active", True)
        if not name:
            raise SkillsServiceError("Missing skill name")
        SkillManager().set_skill_active(name, bool(active))
        return {"name": name, "active": bool(active)}

    async def delete_skill(self, data: object) -> dict:
        self._ensure_mutation_allowed()
        payload = self._payload(data)
        name = payload.get("name")
        if not name:
            raise SkillsServiceError("Missing skill name")
        SkillManager().delete_skill(name)
        try:
            await sync_skills_to_active_sandboxes()
        except Exception:
            logger.warning("Failed to sync deleted skills to active sandboxes.")
        return {"name": name}

    async def get_neo_candidates(self, query: dict[str, Any]) -> SkillsOperationResult:
        logger.info("[Neo] GET /skills/neo/candidates requested.")
        status = query.get("status")
        skill_key = query.get("skill_key")
        limit = int(query.get("limit", 100))
        offset = int(query.get("offset", 0))

        async def _do(client):
            candidates = await client.skills.list_candidates(
                status=status,
                skill_key=skill_key,
                limit=limit,
                offset=offset,
            )
            result = _to_jsonable(candidates)
            total = result.get("total", "?") if isinstance(result, dict) else "?"
            logger.info(f"[Neo] Candidates fetched: total={total}")
            return result

        return await self.with_neo_client(_do)

    async def get_neo_candidates_from_dashboard_query(
        self,
        *,
        status: str | None,
        skill_key: str | None,
        limit: str | None,
        offset: str | None,
    ) -> SkillsOperationResult:
        return await self.get_neo_candidates(
            self._dashboard_query(
                status=status,
                skill_key=skill_key,
                limit=limit,
                offset=offset,
            )
        )

    async def get_neo_releases(self, query: dict[str, Any]) -> SkillsOperationResult:
        logger.info("[Neo] GET /skills/neo/releases requested.")
        skill_key = query.get("skill_key")
        stage = query.get("stage")
        active_only = _to_bool(query.get("active_only"), False)
        limit = int(query.get("limit", 100))
        offset = int(query.get("offset", 0))

        async def _do(client):
            releases = await client.skills.list_releases(
                skill_key=skill_key,
                active_only=active_only,
                stage=stage,
                limit=limit,
                offset=offset,
            )
            result = _to_jsonable(releases)
            total = result.get("total", "?") if isinstance(result, dict) else "?"
            logger.info(f"[Neo] Releases fetched: total={total}")
            return result

        return await self.with_neo_client(_do)

    async def get_neo_releases_from_dashboard_query(
        self,
        *,
        skill_key: str | None,
        stage: str | None,
        active_only: str | None,
        limit: str | None,
        offset: str | None,
    ) -> SkillsOperationResult:
        return await self.get_neo_releases(
            self._dashboard_query(
                skill_key=skill_key,
                stage=stage,
                active_only=active_only,
                limit=limit,
                offset=offset,
            )
        )

    async def get_neo_payload(self, query: dict[str, Any]) -> SkillsOperationResult:
        logger.info("[Neo] GET /skills/neo/payload requested.")
        payload_ref = query.get("payload_ref", "")
        if not payload_ref:
            return SkillsOperationResult(ok=False, message="Missing payload_ref")

        async def _do(client):
            payload = await client.skills.get_payload(payload_ref)
            logger.info(f"[Neo] Payload fetched: ref={payload_ref}")
            return payload

        return await self.with_neo_client(_do)

    async def get_neo_payload_from_dashboard_query(
        self,
        payload_ref: str | None,
    ) -> SkillsOperationResult:
        return await self.get_neo_payload(
            self._dashboard_query(payload_ref=payload_ref)
        )

    async def evaluate_neo_candidate(
        self,
        data: object,
    ) -> SkillsOperationResult:
        self._ensure_mutation_allowed()
        logger.info("[Neo] POST /skills/neo/evaluate requested.")
        payload = self._payload(data)
        candidate_id = payload.get("candidate_id")
        passed_value = payload.get("passed")
        if not candidate_id or passed_value is None:
            return SkillsOperationResult(
                ok=False,
                message="Missing candidate_id or passed",
            )
        passed = _to_bool(passed_value, False)

        async def _do(client):
            result = await client.skills.evaluate_candidate(
                candidate_id,
                passed=passed,
                score=payload.get("score"),
                benchmark_id=payload.get("benchmark_id"),
                report=payload.get("report"),
            )
            logger.info(
                f"[Neo] Candidate evaluated: id={candidate_id}, passed={passed}"
            )
            return result

        return await self.with_neo_client(_do)

    async def promote_neo_candidate(self, data: object) -> SkillsOperationResult:
        self._ensure_mutation_allowed()
        logger.info("[Neo] POST /skills/neo/promote requested.")
        payload = self._payload(data)
        candidate_id = payload.get("candidate_id")
        stage = payload.get("stage", "canary")
        sync_to_local = _to_bool(payload.get("sync_to_local"), True)
        if not candidate_id:
            return SkillsOperationResult(ok=False, message="Missing candidate_id")
        if stage not in {"canary", "stable"}:
            return SkillsOperationResult(
                ok=False,
                message="Invalid stage, must be canary/stable",
            )

        async def _do(client):
            sync_mgr = NeoSkillSyncManager()
            result = await sync_mgr.promote_with_optional_sync(
                client,
                candidate_id=candidate_id,
                stage=stage,
                sync_to_local=sync_to_local,
            )
            release_json = result.get("release")
            logger.info(f"[Neo] Candidate promoted: id={candidate_id}, stage={stage}")

            sync_json = result.get("sync")
            did_sync_to_local = bool(sync_json)
            if did_sync_to_local:
                logger.info(
                    "[Neo] Stable release synced to local: "
                    f"skill={sync_json.get('local_skill_name', '')}"
                )

            if result.get("sync_error"):
                return SkillsOperationResult(
                    ok=False,
                    message=(
                        "Stable promote synced failed and has been rolled back. "
                        f"sync_error={result['sync_error']}"
                    ),
                    data={
                        "release": release_json,
                        "rollback": result.get("rollback"),
                    },
                )

            if not did_sync_to_local:
                try:
                    await sync_skills_to_active_sandboxes()
                except Exception:
                    logger.warning("Failed to sync skills to active sandboxes.")

            return {"release": release_json, "sync": sync_json}

        return await self.with_neo_client(_do)

    async def rollback_neo_release(self, data: object) -> SkillsOperationResult:
        self._ensure_mutation_allowed()
        logger.info("[Neo] POST /skills/neo/rollback requested.")
        payload = self._payload(data)
        release_id = payload.get("release_id")
        if not release_id:
            return SkillsOperationResult(ok=False, message="Missing release_id")

        async def _do(client):
            result = await client.skills.rollback_release(release_id)
            logger.info(f"[Neo] Release rolled back: id={release_id}")
            return result

        return await self.with_neo_client(_do)

    async def sync_neo_release(self, data: object) -> SkillsOperationResult:
        self._ensure_mutation_allowed()
        logger.info("[Neo] POST /skills/neo/sync requested.")
        payload = self._payload(data)
        release_id = payload.get("release_id")
        skill_key = payload.get("skill_key")
        require_stable = _to_bool(payload.get("require_stable"), True)
        if not release_id and not skill_key:
            return SkillsOperationResult(
                ok=False,
                message="Missing release_id or skill_key",
            )

        async def _do(client):
            sync_mgr = NeoSkillSyncManager()
            result = await sync_mgr.sync_release(
                client,
                release_id=release_id,
                skill_key=skill_key,
                require_stable=require_stable,
            )
            logger.info(
                f"[Neo] Release synced to local: skill={result.local_skill_name}, "
                f"release_id={result.release_id}"
            )
            return {
                "skill_key": result.skill_key,
                "local_skill_name": result.local_skill_name,
                "release_id": result.release_id,
                "candidate_id": result.candidate_id,
                "payload_ref": result.payload_ref,
                "map_path": result.map_path,
                "synced_at": result.synced_at,
            }

        return await self.with_neo_client(_do)

    async def delete_neo_candidate(self, data: object) -> SkillsOperationResult:
        self._ensure_mutation_allowed()
        logger.info("[Neo] POST /skills/neo/delete-candidate requested.")
        payload = self._payload(data)
        candidate_id = payload.get("candidate_id")
        reason = payload.get("reason")
        if not candidate_id:
            return SkillsOperationResult(ok=False, message="Missing candidate_id")

        async def _do(client):
            result = await client.skills.delete_candidate(candidate_id, reason=reason)
            logger.info(f"[Neo] Candidate deleted: id={candidate_id}")
            return result

        return await self.with_neo_client(_do)

    async def delete_neo_release(self, data: object) -> SkillsOperationResult:
        self._ensure_mutation_allowed()
        logger.info("[Neo] POST /skills/neo/delete-release requested.")
        payload = self._payload(data)
        release_id = payload.get("release_id")
        reason = payload.get("reason")
        if not release_id:
            return SkillsOperationResult(ok=False, message="Missing release_id")

        async def _do(client):
            result = await client.skills.delete_release(release_id, reason=reason)
            logger.info(f"[Neo] Release deleted: id={release_id}")
            return result

        return await self.with_neo_client(_do)

    async def scan_github_skills(
        self, source: str, proxy: str = ""
    ) -> SkillsOperationResult:
        """Scan a GitHub repository for installable skills.

        Args:
            source: Owner/repo or full repository URL.
            proxy: Proxy URL to prefix requests with.

        Returns:
            SkillsOperationResult containing a list of found skills.
        """
        try:
            skills = await self._scan_skills_from_source(source=source, proxy=proxy)
            return SkillsOperationResult(data={"skills": skills})
        except Exception as e:
            logger.error(traceback.format_exc())
            return SkillsOperationResult(ok=False, message=str(e))

    async def install_skill_from_github(
        self,
        source: str,
        skill_id: str,
        skill_name: str = "",
        proxy: str = "",
    ) -> SkillsOperationResult:
        """Install a skill from a GitHub repository.

        Args:
            source: Owner/repo or full repository URL.
            skill_id: The folder name or ID of the skill.
            skill_name: Optional name of the skill.
            proxy: Proxy URL to prefix requests with.

        Returns:
            SkillsOperationResult containing the name of the installed skill.
        """
        self._ensure_mutation_allowed()
        try:
            logger.info(
                f"Installing skill: source={source}, skillId={skill_id}, name={skill_name}"
            )
            installed_name = await self._install_skill_from_source(
                source=source,
                skill_id=skill_id,
                skill_name=skill_name,
                proxy=proxy,
            )
            logger.info(f"Skill installed successfully: {installed_name}")
            return SkillsOperationResult(
                data={"name": installed_name},
                message="Skill installed successfully.",
            )
        except Exception as e:
            logger.error(f"Failed to install skill: {e}")
            logger.error(traceback.format_exc())
            return SkillsOperationResult(ok=False, message=str(e))

    async def scan_skills_sh_skills(
        self, query: str = "", proxy: str = ""
    ) -> SkillsOperationResult:
        """Scan skills.sh for installable skills.

        Args:
            query: Optional skills.sh URL/id or a local filter for the hot list.
            proxy: Proxy URL to prefix page requests with.

        Returns:
            SkillsOperationResult containing skills that can be installed.
        """
        try:
            query_text = str(query or "").strip()
            skills_sh_path = ""
            if query_text:
                try:
                    skills_sh_path = self._normalize_skills_sh_path(query_text)
                except ValueError:
                    skills_sh_path = ""

            if skills_sh_path:
                skill = await self._build_skills_sh_skill_from_path(
                    skills_sh_path,
                    proxy=proxy,
                )
                return SkillsOperationResult(data={"skills": [skill]})

            skills = await self._scan_skills_sh_hot_list(
                query=query_text,
                proxy=proxy,
            )
            return SkillsOperationResult(data={"skills": skills})
        except Exception as e:
            logger.error(traceback.format_exc())
            return SkillsOperationResult(ok=False, message=str(e))

    async def install_skill_from_skills_sh(
        self,
        skills_sh_path: str,
        skill_id: str = "",
        skill_name: str = "",
        proxy: str = "",
    ) -> SkillsOperationResult:
        """Install a GitHub-backed skill discovered on skills.sh.

        Args:
            skills_sh_path: skills.sh page path or URL for the skill.
            skill_id: Optional skill slug from the scanned item.
            skill_name: Optional display name from the scanned item.
            proxy: Proxy URL to prefix GitHub requests with.

        Returns:
            SkillsOperationResult containing the name of the installed skill.
        """
        self._ensure_mutation_allowed()
        try:
            normalized_path = self._normalize_skills_sh_path(skills_sh_path)
            skill = await self._build_skills_sh_skill_from_path(
                normalized_path,
                proxy=proxy,
            )
            install_url = skill.get("installUrl") or ""
            if "github.com/" not in install_url.lower():
                return SkillsOperationResult(
                    ok=False,
                    message="Only GitHub-backed skills.sh entries can be installed.",
                )

            installed_name = await self._install_skill_from_source(
                source=install_url,
                skill_id=skill_id or skill["skillId"],
                skill_name=skill_name or skill["name"],
                proxy=proxy,
            )
            logger.info(f"skills.sh skill installed successfully: {installed_name}")
            return SkillsOperationResult(
                data={"name": installed_name},
                message="Skill installed successfully.",
            )
        except Exception as e:
            logger.error(f"Failed to install skills.sh skill: {e}")
            logger.error(traceback.format_exc())
            return SkillsOperationResult(ok=False, message=str(e))

    async def _scan_skills_from_source(
        self,
        source: str,
        proxy: str = "",
    ) -> list[dict[str, str]]:
        owner, repo = self._parse_github_source(source)
        repo_zip_path = await self._download_github_repo_zip(owner, repo, proxy=proxy)
        try:
            candidates = await asyncio.to_thread(
                self._collect_skill_candidates_from_repo_zip,
                repo_zip_path,
            )
            return [
                {
                    "skillId": candidate["folder_name"],
                    "name": candidate.get("frontmatter_name")
                    or candidate["folder_name"],
                    "source": source,
                    "path": candidate["skill_dir"],
                }
                for candidate in candidates
            ]
        finally:
            if repo_zip_path and await asyncio.to_thread(os.path.exists, repo_zip_path):
                try:
                    await asyncio.to_thread(os.unlink, repo_zip_path)
                except Exception:
                    logger.warning(f"Failed to remove temp skill file: {repo_zip_path}")

    async def _install_skill_from_source(
        self,
        source: str,
        skill_id: str,
        skill_name: str = "",
        proxy: str = "",
    ) -> str:
        owner, repo = self._parse_github_source(source)
        logger.info(
            f"Downloading repository: {owner}/{repo} (proxy: {'yes' if proxy else 'no'})"
        )
        repo_zip_path = await self._download_github_repo_zip(owner, repo, proxy=proxy)
        single_skill_zip_path = None
        try:
            logger.info(f"Extracting skill '{skill_id}' from repository")
            single_skill_zip_path = await asyncio.to_thread(
                self._build_single_skill_zip_from_repo_zip,
                repo_zip_path,
                skill_id,
                skill_name,
            )
            skill_manager = SkillManager()
            return await asyncio.to_thread(
                skill_manager.install_skill_from_zip,
                single_skill_zip_path,
                overwrite=True,
            )
        finally:
            for temp_path in (repo_zip_path, single_skill_zip_path):
                if temp_path and await asyncio.to_thread(os.path.exists, temp_path):
                    try:
                        await asyncio.to_thread(os.unlink, temp_path)
                    except Exception:
                        logger.warning(f"Failed to remove temp skill file: {temp_path}")

    def _normalize_skills_sh_path(self, source: str) -> str:
        source_text = str(source or "").strip()
        if not source_text:
            raise ValueError("Missing skills.sh source.")
        if source_text.startswith("skills.sh/") or source_text.startswith(
            "www.skills.sh/"
        ):
            source_text = f"https://{source_text}"

        parsed = urlparse(source_text)
        if parsed.scheme:
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("Invalid skills.sh source.")
            if parsed.netloc.lower() not in _SKILLS_SH_HOSTS:
                raise ValueError("Only skills.sh sources are supported.")
            segments = [segment for segment in parsed.path.split("/") if segment]
        else:
            segments = [
                segment for segment in source_text.strip("/").split("/") if segment
            ]

        if not segments or segments[0] in {
            "api",
            "docs",
            "hot",
            "official",
            "security",
            "topics",
            "trending",
        }:
            raise ValueError("A skills.sh skill URL or id is required.")
        if len(segments) < 3:
            raise ValueError("Invalid skills.sh skill id.")

        if segments[0] == "site":
            if len(segments) < 3:
                raise ValueError("Invalid skills.sh site skill id.")
            selected = segments[:3]
        else:
            selected = segments[:3]

        if any(not _SKILL_FOLDER_RE.match(segment) for segment in selected):
            raise ValueError("Invalid skills.sh skill id.")
        return "/".join(selected)

    async def _fetch_skills_sh_page(self, page_url: str, proxy: str = "") -> str:
        normalized_proxy = self._normalize_proxy_value(proxy)
        request_url = (
            self._apply_github_proxy(page_url, normalized_proxy)
            if normalized_proxy
            else page_url
        )
        timeout = aiohttp.ClientTimeout(total=30)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        headers = {"User-Agent": "AstrBot/SkillsFetcher"}
        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=timeout,
            connector=connector,
        ) as session:
            async with session.get(request_url, headers=headers) as response:
                if response.status != 200:
                    raise ValueError(
                        f"Failed to fetch skills.sh page: status={response.status}"
                    )
                return await response.text()

    @staticmethod
    def _html_to_text(value: str) -> str:
        no_comments = re.sub(r"<!--.*?-->", " ", value, flags=re.DOTALL)
        no_tags = re.sub(r"<[^>]+>", " ", no_comments)
        return " ".join(html.unescape(no_tags).split())

    async def _scan_skills_sh_hot_list(
        self,
        query: str = "",
        proxy: str = "",
    ) -> list[dict[str, str]]:
        page_html = await self._fetch_skills_sh_page(
            f"{_SKILLS_SH_BASE_URL}/hot",
            proxy=proxy,
        )
        query_lower = query.strip().lower()
        skills: list[dict[str, str]] = []
        seen_paths: set[str] = set()

        for match in _SKILLS_SH_LINK_RE.finditer(page_html):
            href = html.unescape(match.group("href"))
            segments = [segment for segment in href.strip("/").split("/") if segment]
            if len(segments) < 3:
                continue
            if segments[0] == "site":
                selected = segments[:3]
                source = selected[1]
                skill_id = selected[2]
                install_url = ""
            else:
                selected = segments[:3]
                source = f"{selected[0]}/{selected[1]}"
                skill_id = selected[2]
                install_url = f"https://github.com/{source}"
            if any(not _SKILL_FOLDER_RE.match(segment) for segment in selected):
                continue

            skills_sh_path = "/".join(selected)
            if skills_sh_path in seen_paths:
                continue
            seen_paths.add(skills_sh_path)

            display_text = self._html_to_text(match.group("body"))
            name = skill_id
            text_parts = display_text.split()
            if len(text_parts) >= 2 and text_parts[0].isdigit():
                name = text_parts[1]

            searchable = f"{name} {source} {skill_id}".lower()
            if query_lower and query_lower not in searchable:
                continue

            skills.append(
                {
                    "skillId": skill_id,
                    "name": name,
                    "source": source,
                    "sourceType": "skills_sh",
                    "skillsShPath": skills_sh_path,
                    "installUrl": install_url,
                    "path": f"{_SKILLS_SH_BASE_URL}/{skills_sh_path}",
                }
            )
            if len(skills) >= 50:
                break

        return skills

    async def _build_skills_sh_skill_from_path(
        self,
        skills_sh_path: str,
        proxy: str = "",
    ) -> dict[str, str]:
        page_html = await self._fetch_skills_sh_page(
            f"{_SKILLS_SH_BASE_URL}/{skills_sh_path}",
            proxy=proxy,
        )
        page_text = self._html_to_text(page_html)
        command_match = _SKILLS_SH_INSTALL_RE.search(page_text)
        segments = skills_sh_path.split("/")
        skill_id = segments[-1]
        name = skill_id
        title_match = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.DOTALL)
        if title_match:
            title = self._html_to_text(title_match.group(1))
            if title:
                name = title

        if command_match:
            install_url = command_match.group("target").strip()
            skill_id = (command_match.group("skill") or skill_id).strip()
        elif segments[0] != "site":
            source = f"{segments[0]}/{segments[1]}"
            install_url = f"https://github.com/{source}"
        else:
            install_url = ""

        source = (
            segments[1] if segments[0] == "site" else f"{segments[0]}/{segments[1]}"
        )
        parsed_install = urlparse(install_url)
        if parsed_install.netloc.lower() in {"github.com", "www.github.com"}:
            install_segments = [
                segment for segment in parsed_install.path.split("/") if segment
            ]
            if len(install_segments) >= 2:
                source = (
                    f"{install_segments[0]}/{install_segments[1].removesuffix('.git')}"
                )

        return {
            "skillId": skill_id,
            "name": name,
            "source": source,
            "sourceType": "skills_sh",
            "skillsShPath": skills_sh_path,
            "installUrl": install_url,
            "path": f"{_SKILLS_SH_BASE_URL}/{skills_sh_path}",
        }

    def _parse_github_source(self, source: str) -> tuple[str, str]:
        source = source.strip()
        match = _GITHUB_SOURCE_RE.match(source)
        if match:
            return match.group("owner"), match.group("repo")

        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only GitHub sources are supported.")
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("Only GitHub sources are supported.")

        segments = [seg for seg in parsed.path.split("/") if seg]
        if len(segments) < 2:
            raise ValueError("Invalid GitHub repository source.")

        owner = segments[0]
        repo = segments[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not owner or not repo:
            raise ValueError("Invalid GitHub repository source.")
        return owner, repo

    def _normalize_proxy_value(self, proxy: Any) -> str:
        if proxy is None:
            return ""
        normalized = str(proxy).strip()
        if not normalized:
            return ""
        return normalized.rstrip("/")

    def _apply_github_proxy(self, url: str, proxy: str = "") -> str:
        if not proxy:
            return url
        return f"{proxy}/{url}"

    async def _fetch_default_branch(
        self,
        session: aiohttp.ClientSession,
        owner: str,
        repo: str,
        proxy: str = "",
    ) -> str | None:
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        candidate_urls = [api_url]
        if proxy:
            candidate_urls.insert(0, self._apply_github_proxy(api_url, proxy))

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AstrBot/SkillsFetcher",
        }
        for request_url in candidate_urls:
            try:
                async with session.get(request_url, headers=headers) as response:
                    if response.status != 200:
                        continue
                    payload = await response.json()
                    branch = payload.get("default_branch")
                    if isinstance(branch, str) and branch.strip():
                        return branch.strip()
            except Exception:
                continue
        return None

    async def _download_github_repo_zip(
        self,
        owner: str,
        repo: str,
        proxy: str = "",
    ) -> str:
        normalized_proxy = self._normalize_proxy_value(proxy)
        timeout = aiohttp.ClientTimeout(total=60)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        headers = {"User-Agent": "AstrBot/SkillsFetcher"}
        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=timeout,
            connector=connector,
        ) as session:
            preferred_branch = await self._fetch_default_branch(
                session,
                owner,
                repo,
                proxy=normalized_proxy,
            )
            branch_candidates = []
            if preferred_branch:
                branch_candidates.append(preferred_branch)
            branch_candidates.extend(["main", "master"])

            seen_branches: set[str] = set()
            for branch in branch_candidates:
                if branch in seen_branches:
                    continue
                seen_branches.add(branch)
                branch_ref = quote(branch, safe="")
                archive_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch_ref}"

                request_urls = [archive_url]
                if normalized_proxy:
                    request_urls.insert(
                        0, self._apply_github_proxy(archive_url, normalized_proxy)
                    )

                for request_url in request_urls:
                    try:
                        logger.info(
                            f"Attempting to download {owner}/{repo} from branch '{branch}'"
                        )
                        async with session.get(
                            request_url, headers=headers
                        ) as response:
                            if response.status != 200:
                                logger.warning(
                                    f"Download failed with status {response.status} for branch '{branch}'"
                                )
                                continue
                            await asyncio.to_thread(
                                os.makedirs,
                                get_astrbot_temp_path(),
                                exist_ok=True,
                            )
                            fd, archive_path = tempfile.mkstemp(
                                prefix=f"{repo}-",
                                suffix=".zip",
                                dir=get_astrbot_temp_path(),
                            )
                            os.close(fd)
                            file_handle = await asyncio.to_thread(
                                open, archive_path, "wb"
                            )
                            try:
                                async for chunk in response.content.iter_chunked(
                                    64 * 1024
                                ):
                                    await asyncio.to_thread(file_handle.write, chunk)
                            finally:
                                await asyncio.to_thread(file_handle.close)
                            logger.info(
                                f"Successfully downloaded {owner}/{repo} (branch: {branch})"
                            )
                            return archive_path
                    except Exception as e:
                        logger.warning(f"Download error for branch '{branch}': {e}")
                        continue

        raise ValueError("Failed to download GitHub repository archive.")

    def _build_single_skill_zip_from_repo_zip(
        self,
        repo_zip_path: str,
        skill_id: str,
        skill_name: str = "",
    ) -> str:
        requested_lower = skill_id.strip().lower()
        requested_slug = _slugify(skill_id)
        requested_name_slug = _slugify(skill_name)
        if not requested_lower and not requested_slug:
            raise ValueError("Invalid skill id.")

        with zipfile.ZipFile(repo_zip_path) as repo_zip:
            candidates = self._collect_skill_candidates(repo_zip)
            selected = self._select_skill_candidate(
                candidates=candidates,
                requested_lower=requested_lower,
                requested_slug=requested_slug,
                requested_name_slug=requested_name_slug,
            )

            install_folder = skill_id if _SKILL_FOLDER_RE.match(skill_id) else ""
            if not install_folder:
                install_folder = selected["folder_name"]
            if not _SKILL_FOLDER_RE.match(install_folder):
                install_folder = _slugify(install_folder)
            if not install_folder or not _SKILL_FOLDER_RE.match(install_folder):
                raise ValueError("Selected skill has an invalid install folder name.")

            prefix = selected["skill_dir"].rstrip("/") + "/"
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".zip",
                dir=get_astrbot_temp_path(),
            ) as temp_zip:
                skill_zip_path = temp_zip.name

            with zipfile.ZipFile(
                skill_zip_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as out_zip:
                for info in repo_zip.infolist():
                    normalized = info.filename.replace("\\", "/")
                    if not normalized.startswith(prefix):
                        continue
                    relative_path = normalized[len(prefix) :]
                    if not relative_path:
                        continue
                    rel_parts = Path(relative_path).parts
                    if any(part in {"", ".", ".."} for part in rel_parts):
                        continue
                    target_path = f"{install_folder}/{relative_path}"
                    if info.is_dir():
                        out_zip.writestr(target_path.rstrip("/") + "/", b"")
                    else:
                        out_zip.writestr(target_path, repo_zip.read(info.filename))

        return skill_zip_path

    def _collect_skill_candidates_from_repo_zip(
        self, repo_zip_path: str
    ) -> list[dict[str, str]]:
        with zipfile.ZipFile(repo_zip_path) as repo_zip:
            return self._collect_skill_candidates(repo_zip)

    def _collect_skill_candidates(
        self, repo_zip: zipfile.ZipFile
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen_dirs: set[str] = set()
        for info in repo_zip.infolist():
            if info.is_dir():
                continue
            normalized = info.filename.replace("\\", "/")
            if not normalized.lower().endswith("/skill.md"):
                continue
            parts = Path(normalized).parts
            if any(part in {"", ".", ".."} for part in parts):
                continue
            skill_dir = str(Path(normalized).parent).replace("\\", "/")
            if not skill_dir or skill_dir in seen_dirs:
                continue
            seen_dirs.add(skill_dir)
            folder_name = Path(skill_dir).name
            try:
                skill_md_text = repo_zip.read(info.filename).decode(
                    "utf-8", errors="ignore"
                )
            except Exception:
                skill_md_text = ""
            frontmatter_name = _parse_frontmatter_value(skill_md_text, "name")
            candidates.append(
                {
                    "skill_dir": skill_dir,
                    "folder_name": folder_name,
                    "frontmatter_name": frontmatter_name,
                }
            )
        if not candidates:
            raise ValueError("No SKILL.md found in the repository archive.")
        return candidates

    def _select_skill_candidate(
        self,
        *,
        candidates: list[dict[str, str]],
        requested_lower: str,
        requested_slug: str,
        requested_name_slug: str,
    ) -> dict[str, str]:
        scored_matches: list[tuple[int, dict[str, str]]] = []
        for candidate in candidates:
            folder_lower = candidate["folder_name"].lower()
            folder_slug = _slugify(candidate["folder_name"])
            frontmatter_name = candidate.get("frontmatter_name", "")
            frontmatter_lower = frontmatter_name.lower()
            frontmatter_slug = _slugify(frontmatter_name)

            score = -1
            if requested_lower and requested_lower == folder_lower:
                score = 500
            elif (
                requested_lower
                and frontmatter_lower
                and requested_lower == frontmatter_lower
            ):
                score = 450
            elif requested_slug and requested_slug == folder_slug:
                score = 400
            elif (
                requested_slug
                and frontmatter_slug
                and requested_slug == frontmatter_slug
            ):
                score = 350
            elif requested_name_slug and requested_name_slug == frontmatter_slug:
                score = 320
            elif requested_name_slug and requested_name_slug == folder_slug:
                score = 300

            if score >= 0:
                scored_matches.append((score, candidate))

        if not scored_matches:
            available = ", ".join(sorted(c["folder_name"] for c in candidates[:20]))
            raise ValueError(
                f"Skill '{requested_lower or requested_slug}' not found. "
                f"Available skills include: {available}"
            )

        scored_matches.sort(key=lambda item: item[0], reverse=True)
        best_score = scored_matches[0][0]
        best_matches = [
            candidate for score, candidate in scored_matches if score == best_score
        ]
        if len(best_matches) > 1:
            matched_names = ", ".join(
                sorted(item["folder_name"] for item in best_matches)
            )
            raise ValueError(
                f"Multiple skills match the requested id. Please use a more specific id. "
                f"Matches: {matched_names}"
            )
        return best_matches[0]

    @staticmethod
    def _dashboard_query(**values: Any) -> dict[str, Any]:
        return {
            key: value
            for key, value in values.items()
            if value is not None and value != ""
        }
