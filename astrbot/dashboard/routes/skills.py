import asyncio
import os
import re
import shutil
import ssl
import tempfile
import traceback
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
import certifi
from quart import request, send_file

from astrbot.core import DEMO_MODE, logger
from astrbot.core.computer.computer_client import (
    _discover_bay_credentials,
    sync_skills_to_active_sandboxes,
)
from astrbot.core.skills.neo_skill_sync import NeoSkillSyncManager
from astrbot.core.skills.skill_manager import SkillManager
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from .route import Response, Route, RouteContext

_GITHUB_SOURCE_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$"
)
_SKILL_FOLDER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {
    ".md",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".txt",
    ".toml",
    ".ini",
    ".cfg",
}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _validate_file_path(file_path: str) -> bool:
    """Validate that file_path doesn't contain path traversal."""
    # Check for ../ patterns
    if "../" in file_path or "..\\" in file_path:
        return False
    # Check for leading ./
    if file_path.startswith("./") or file_path.startswith(".\\"):
        return False
    # Normalize the path and ensure it doesn't start with ..
    normalized = Path(file_path).as_posix()
    if normalized.startswith(".."):
        return False
    return True


def _validate_file_extension(file_path: str) -> bool:
    """Validate that file has an allowed extension."""
    ext = Path(file_path).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


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


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
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


_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _next_available_temp_path(temp_dir: str, filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    index = 1
    while os.path.exists(os.path.join(temp_dir, candidate)):
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    return os.path.join(temp_dir, candidate)


class SkillsRoute(Route):
    def __init__(self, context: RouteContext, core_lifecycle) -> None:
        super().__init__(context)
        self.core_lifecycle = core_lifecycle
        self.routes = {
            "/skills": ("GET", self.get_skills),
            "/skills/detail": ("GET", self.get_skill_detail),
            "/skills/file": ("GET", self.get_file_content),
            "/skills/github/scan": ("POST", self.scan_github_skills),
            "/skills/install": ("POST", self.install_skill),
            "/skills/upload": ("POST", self.upload_skill),
            "/skills/batch-upload": ("POST", self.batch_upload_skills),
            "/skills/download": ("GET", self.download_skill),
            "/skills/update": ("POST", self.update_skill),
            "/skills/update_detail": ("POST", self.update_skill_detail),
            "/skills/delete": ("POST", self.delete_skill),
            "/skills/neo/candidates": ("GET", self.get_neo_candidates),
            "/skills/neo/releases": ("GET", self.get_neo_releases),
            "/skills/neo/payload": ("GET", self.get_neo_payload),
            "/skills/neo/evaluate": ("POST", self.evaluate_neo_candidate),
            "/skills/neo/promote": ("POST", self.promote_neo_candidate),
            "/skills/neo/rollback": ("POST", self.rollback_neo_release),
            "/skills/neo/sync": ("POST", self.sync_neo_release),
            "/skills/neo/delete-candidate": ("POST", self.delete_neo_candidate),
            "/skills/neo/delete-release": ("POST", self.delete_neo_release),
        }
        self.register_routes()

    def _get_neo_client_config(self) -> tuple[str, str]:
        provider_settings = self.core_lifecycle.astrbot_config.get(
            "provider_settings",
            {},
        )
        sandbox = provider_settings.get("sandbox", {})
        endpoint = sandbox.get("shipyard_neo_endpoint", "")
        access_token = sandbox.get("shipyard_neo_access_token", "")

        # Auto-discover token from Bay's credentials.json if not configured
        if not access_token and endpoint:
            access_token = _discover_bay_credentials(endpoint)

        if not endpoint or not access_token:
            raise ValueError(
                "Shipyard Neo endpoint or access token not configured. "
                "Set them in Dashboard or ensure Bay's credentials.json is accessible."
            )
        return endpoint, access_token

    async def _delete_neo_release(
        self, client: Any, release_id: str, reason: str | None
    ):
        return await client.skills.delete_release(release_id, reason=reason)

    async def _delete_neo_candidate(
        self, client: Any, candidate_id: str, reason: str | None
    ):
        return await client.skills.delete_candidate(candidate_id, reason=reason)

    async def _with_neo_client(
        self,
        operation: Callable[[Any], Awaitable[dict]],
    ) -> dict:
        try:
            endpoint, access_token = self._get_neo_client_config()

            from shipyard_neo import BayClient

            async with BayClient(
                endpoint_url=endpoint,
                access_token=access_token,
            ) as client:
                return await operation(client)
        except ValueError as e:
            # Config not ready — expected when Neo isn't set up yet
            logger.debug("[Neo] %s", e)
            return Response().error(str(e)).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def get_skills(self):
        try:
            provider_settings = self.core_lifecycle.astrbot_config.get(
                "provider_settings", {}
            )
            runtime = provider_settings.get("computer_use_runtime", "local")
            skill_mgr = SkillManager()
            skills = skill_mgr.list_skills(
                active_only=False, runtime=runtime, show_sandbox_path=False
            )
            return (
                Response()
                .ok(
                    {
                        "skills": [skill.__dict__ for skill in skills],
                        "runtime": runtime,
                        "sandbox_cache": skill_mgr.get_sandbox_skills_cache_status(),
                    }
                )
                .__dict__
            )
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def scan_github_skills(self):
        try:
            data = await request.get_json(silent=True) or {}
            source = str(data.get("repo", "") or data.get("source", "")).strip()
            proxy = self._normalize_proxy_value(
                data.get("proxy")
                or data.get("githubProxy")
                or data.get("proxy_url")
                or ""
            )

            if not source:
                return Response().error("Missing GitHub repository source").__dict__

            skills = await self._scan_skills_from_source(source=source, proxy=proxy)
            return Response().ok({"skills": skills}).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def install_skill(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        try:
            data = await request.get_json(silent=True) or {}
            source = str(data.get("source", "") or data.get("repo", "")).strip()
            skill_id = str(data.get("skillId", "") or data.get("skill_id", "")).strip()
            skill_name = str(data.get("name", "")).strip()
            proxy = self._normalize_proxy_value(
                data.get("proxy")
                or data.get("githubProxy")
                or data.get("proxy_url")
                or ""
            )

            if not source:
                return Response().error("Missing skill source").__dict__
            if not skill_id:
                return Response().error("Missing skill id").__dict__

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
            return (
                Response()
                .ok({"name": installed_name}, "Skill installed successfully.")
                .__dict__
            )
        except Exception as e:
            logger.error(f"Failed to install skill: {e}")
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def upload_skill(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )

        temp_path = None
        try:
            files = await request.files
            file = files.get("file")
            if not file:
                return Response().error("Missing file").__dict__
            filename = Path(file.filename or "skill.zip").name
            if not filename.lower().endswith(".zip"):
                return Response().error("Only .zip files are supported").__dict__

            temp_dir = get_astrbot_temp_path()
            await asyncio.to_thread(os.makedirs, temp_dir, exist_ok=True)
            skill_mgr = SkillManager()
            temp_path = _next_available_temp_path(temp_dir, filename)
            await file.save(temp_path)

            try:
                try:
                    skill_name = skill_mgr.install_skill_from_zip(
                        temp_path, overwrite=False, skill_name_hint=Path(filename).stem
                    )
                except TypeError:
                    # Backward compatibility for callers that do not accept skill_name_hint
                    skill_name = skill_mgr.install_skill_from_zip(
                        temp_path, overwrite=False
                    )
            except Exception:
                # Keep behavior consistent with previous implementation
                # and bubble up install errors (including duplicates).
                raise

            try:
                await sync_skills_to_active_sandboxes()
            except Exception:
                logger.warning("Failed to sync uploaded skills to active sandboxes.")

            return (
                Response()
                .ok({"name": skill_name}, "Skill uploaded successfully.")
                .__dict__
            )
        except Exception as e:
            logger.error(f"Failed to upload skill: {e}")
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    await asyncio.to_thread(os.unlink, temp_path)
                except Exception:
                    logger.warning(f"Failed to remove temp skill file: {temp_path}")

    async def batch_upload_skills(self):
        """批量上传多个 skill ZIP 文件"""
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )

        try:
            files = await request.files
            file_list = files.getlist("files")

            if not file_list:
                return Response().error("No files provided").__dict__

            succeeded = []
            failed = []
            skipped = []
            skill_mgr = SkillManager()
            temp_dir = get_astrbot_temp_path()
            await asyncio.to_thread(os.makedirs, temp_dir, exist_ok=True)

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
                    await file.save(temp_path)

                    try:
                        skill_name = skill_mgr.install_skill_from_zip(
                            temp_path,
                            overwrite=False,
                            skill_name_hint=Path(filename).stem,
                        )
                    except TypeError:
                        # Backward compatibility for monkeypatched implementations in tests
                        try:
                            skill_name = skill_mgr.install_skill_from_zip(
                                temp_path, overwrite=False
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

                except Exception as e:
                    failed.append({"filename": filename, "error": str(e)})
                finally:
                    if temp_path and await asyncio.to_thread(os.path.exists, temp_path):
                        try:
                            await asyncio.to_thread(os.remove, temp_path)
                        except Exception:
                            pass

            if succeeded:
                try:
                    await sync_skills_to_active_sandboxes()
                except Exception:
                    logger.warning(
                        "Failed to sync uploaded skills to active sandboxes."
                    )

            total = len(file_list)
            success_count = len(succeeded)
            skipped_count = len(skipped)
            failed_count = len(failed)

            if failed_count == 0 and success_count == total:
                message = f"All {total} skill(s) uploaded successfully."
                return (
                    Response()
                    .ok(
                        {
                            "total": total,
                            "succeeded": succeeded,
                            "failed": failed,
                            "skipped": skipped,
                        },
                        message,
                    )
                    .__dict__
                )
            if failed_count == 0 and success_count == 0:
                message = f"All {total} file(s) were skipped."
                return (
                    Response()
                    .ok(
                        {
                            "total": total,
                            "succeeded": succeeded,
                            "failed": failed,
                            "skipped": skipped,
                        },
                        message,
                    )
                    .__dict__
                )
            if success_count == 0 and skipped_count == 0:
                message = f"Upload failed for all {total} file(s)."
                resp = Response().error(message)
                resp.data = {
                    "total": total,
                    "succeeded": succeeded,
                    "failed": failed,
                    "skipped": skipped,
                }
                return resp.__dict__

            message = f"Partial success: {success_count}/{total} skill(s) uploaded."
            return (
                Response()
                .ok(
                    {
                        "total": total,
                        "succeeded": succeeded,
                        "failed": failed,
                        "skipped": skipped,
                    },
                    message,
                )
                .__dict__
            )

        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def download_skill(self):
        try:
            name = str(request.args.get("name") or "").strip()
            if not name:
                return Response().error("Missing skill name").__dict__
            if not _SKILL_NAME_RE.match(name):
                return Response().error("Invalid skill name").__dict__

            skill_mgr = SkillManager()
            if skill_mgr.is_sandbox_only_skill(name):
                return (
                    Response()
                    .error(
                        "Sandbox preset skill cannot be downloaded from local skill files."
                    )
                    .__dict__
                )

            skill_dir = Path(skill_mgr.skills_root) / name
            skill_md = skill_dir / "SKILL.md"
            if not skill_dir.is_dir() or not skill_md.exists():
                return Response().error("Local skill not found").__dict__

            export_dir = Path(get_astrbot_temp_path()) / "skill_exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            zip_base = export_dir / name
            zip_path = zip_base.with_suffix(".zip")
            if zip_path.exists():
                zip_path.unlink()

            shutil.make_archive(
                str(zip_base),
                "zip",
                root_dir=str(skill_mgr.skills_root),
                base_dir=name,
            )

            return await send_file(
                str(zip_path),
                as_attachment=True,
                attachment_filename=f"{name}.zip",
                conditional=True,
            )
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def update_skill(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        try:
            data = await request.get_json()
            name = data.get("name")
            active = data.get("active", True)
            if not name:
                return Response().error("Missing skill name").__dict__
            logger.info(f"Updating skill: {name} (active={active})")
            SkillManager().set_skill_active(name, bool(active))
            logger.info(f"Skill updated successfully: {name}")
            return Response().ok({"name": name, "active": bool(active)}).__dict__
        except Exception as e:
            logger.error(f"Failed to update skill: {e}")
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def delete_skill(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        try:
            data = await request.get_json()
            name = data.get("name")
            if not name:
                return Response().error("Missing skill name").__dict__
            logger.info(f"Deleting skill: {name}")
            SkillManager().delete_skill(name)
            try:
                await sync_skills_to_active_sandboxes()
            except Exception:
                logger.warning("Failed to sync deleted skills to active sandboxes.")
            logger.info(f"Skill deleted successfully: {name}")
            return Response().ok({"name": name}).__dict__
        except Exception as e:
            logger.error(f"Failed to delete skill: {e}")
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def _scan_skills_from_source(
        self,
        *,
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
        *,
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
            candidate_urls = [candidate_urls[0]]

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
        *,
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

                request_url = archive_url
                if normalized_proxy:
                    request_url = self._apply_github_proxy(
                        archive_url, normalized_proxy
                    )

                try:
                    logger.info(
                        f"Attempting to download {owner}/{repo} from branch '{branch}'"
                    )
                    async with session.get(request_url, headers=headers) as response:
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
                        file_handle = await asyncio.to_thread(open, archive_path, "wb")
                        try:
                            async for chunk in response.content.iter_chunked(64 * 1024):
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

    def _build_file_tree(self, root_path: Path) -> list[dict]:
        """Build a file tree structure from a directory."""
        if not root_path.exists() or not root_path.is_dir():
            return []

        tree = []

        def _scan_dir(path: Path, tree_list: list, base_path: Path):
            for item in sorted(path.iterdir()):
                relative_path = item.relative_to(base_path)
                if item.is_dir():
                    node = {
                        "name": item.name,
                        "path": str(relative_path),
                        "type": "directory",
                        "children": [],
                    }
                    tree_list.append(node)
                    _scan_dir(item, node["children"], base_path)
                else:
                    tree_list.append(
                        {
                            "name": item.name,
                            "path": str(relative_path),
                            "type": "file",
                            "size": item.stat().st_size,
                        }
                    )

        _scan_dir(root_path, tree, root_path)
        return tree

    async def get_skill_detail(self):
        name = request.args.get("name", "").strip()
        if not name:
            return Response().error("Missing skill name").__dict__
        try:
            skill_manager = SkillManager()
            skills = skill_manager.list_skills(
                active_only=False, show_sandbox_path=False
            )
            skill = next((s for s in skills if s.name == name), None)
            if not skill:
                return Response().error("Skill not found").__dict__
            skill_path = Path(skill_manager.skills_root) / name
            if not skill_path.exists():
                return Response().error("Skill directory not found").__dict__
            file_tree = self._build_file_tree(skill_path)
            return (
                Response()
                .ok(
                    {
                        "name": skill.name,
                        "description": skill.description,
                        "path": skill.path,
                        "active": skill.active,
                        "files": file_tree,
                    }
                )
                .__dict__
            )
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def get_file_content(self):
        name = request.args.get("name", "").strip()
        file_path = request.args.get("file", "").strip()
        if not name:
            return Response().error("Missing skill name").__dict__
        if not file_path:
            return Response().error("Missing file path").__dict__
        if not _validate_file_path(file_path):
            return Response().error("Invalid file path").__dict__
        try:
            skill_manager = SkillManager()
            skills = skill_manager.list_skills(
                active_only=False, show_sandbox_path=False
            )
            skill = next((s for s in skills if s.name == name), None)
            if not skill:
                return Response().error("Skill not found").__dict__
            full_path = Path(skill_manager.skills_root) / name / file_path
            if not full_path.exists():
                return Response().error("File not found").__dict__
            if not full_path.is_file():
                return Response().error("Not a file").__dict__
            file_size = full_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                return (
                    Response()
                    .error(f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")
                    .__dict__
                )
            content = await asyncio.to_thread(full_path.read_text, encoding="utf-8")
            return (
                Response()
                .ok(
                    {
                        "name": skill.name,
                        "file_path": file_path,
                        "content": content,
                    }
                )
                .__dict__
            )
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def update_skill_detail(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        try:
            data = await request.get_json()
            name = data.get("name", "").strip()
            file_path = data.get("file_path", "SKILL.md").strip()
            content = data.get("content", "").strip()
            if not name:
                return Response().error("Missing skill name").__dict__
            if not content:
                return Response().error("Missing content").__dict__
            if not _validate_file_path(file_path):
                return Response().error("Invalid file path").__dict__
            skill_manager = SkillManager()
            skills = skill_manager.list_skills(
                active_only=False, show_sandbox_path=False
            )
            skill = next((s for s in skills if s.name == name), None)
            if not skill:
                return Response().error("Skill not found").__dict__
            full_path = Path(skill_manager.skills_root) / name / file_path
            if not full_path.exists():
                return Response().error("File not found").__dict__
            if not full_path.is_file():
                return Response().error("Not a file").__dict__
            await asyncio.to_thread(full_path.write_text, content, encoding="utf-8")
            logger.info(f"Skill file updated: {name}/{file_path}")
            return Response().ok({"name": name, "file_path": file_path}).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def get_neo_candidates(self):
        logger.info("[Neo] GET /skills/neo/candidates requested.")
        status = request.args.get("status")
        skill_key = request.args.get("skill_key")
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))

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
            return Response().ok(result).__dict__

        return await self._with_neo_client(_do)

    async def get_neo_releases(self):
        logger.info("[Neo] GET /skills/neo/releases requested.")
        skill_key = request.args.get("skill_key")
        stage = request.args.get("stage")
        active_only = _to_bool(request.args.get("active_only"), False)
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))

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
            return Response().ok(result).__dict__

        return await self._with_neo_client(_do)

    async def get_neo_payload(self):
        logger.info("[Neo] GET /skills/neo/payload requested.")
        payload_ref = request.args.get("payload_ref", "")
        if not payload_ref:
            return Response().error("Missing payload_ref").__dict__

        async def _do(client):
            payload = await client.skills.get_payload(payload_ref)
            logger.info(f"[Neo] Payload fetched: ref={payload_ref}")
            return Response().ok(_to_jsonable(payload)).__dict__

        return await self._with_neo_client(_do)

    async def evaluate_neo_candidate(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        logger.info("[Neo] POST /skills/neo/evaluate requested.")
        data = await request.get_json()
        candidate_id = data.get("candidate_id")
        passed_value = data.get("passed")
        if not candidate_id or passed_value is None:
            return Response().error("Missing candidate_id or passed").__dict__
        passed = _to_bool(passed_value, False)

        async def _do(client):
            result = await client.skills.evaluate_candidate(
                candidate_id,
                passed=passed,
                score=data.get("score"),
                benchmark_id=data.get("benchmark_id"),
                report=data.get("report"),
            )
            logger.info(
                f"[Neo] Candidate evaluated: id={candidate_id}, passed={passed}"
            )
            return Response().ok(_to_jsonable(result)).__dict__

        return await self._with_neo_client(_do)

    async def promote_neo_candidate(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        logger.info("[Neo] POST /skills/neo/promote requested.")
        data = await request.get_json()
        candidate_id = data.get("candidate_id")
        stage = data.get("stage", "canary")
        sync_to_local = _to_bool(data.get("sync_to_local"), True)
        if not candidate_id:
            return Response().error("Missing candidate_id").__dict__
        if stage not in {"canary", "stable"}:
            return Response().error("Invalid stage, must be canary/stable").__dict__

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
                    f"[Neo] Stable release synced to local: skill={sync_json.get('local_skill_name', '')}"
                )

            if result.get("sync_error"):
                resp = Response().error(
                    "Stable promote synced failed and has been rolled back. "
                    f"sync_error={result['sync_error']}"
                )
                resp.data = {
                    "release": release_json,
                    "rollback": result.get("rollback"),
                }
                return resp.__dict__

            # Try to push latest local skills to all active sandboxes.
            if not did_sync_to_local:
                try:
                    await sync_skills_to_active_sandboxes()
                except Exception:
                    logger.warning("Failed to sync skills to active sandboxes.")

            return Response().ok({"release": release_json, "sync": sync_json}).__dict__

        return await self._with_neo_client(_do)

    async def rollback_neo_release(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        logger.info("[Neo] POST /skills/neo/rollback requested.")
        data = await request.get_json()
        release_id = data.get("release_id")
        if not release_id:
            return Response().error("Missing release_id").__dict__

        async def _do(client):
            result = await client.skills.rollback_release(release_id)
            logger.info(f"[Neo] Release rolled back: id={release_id}")
            return Response().ok(_to_jsonable(result)).__dict__

        return await self._with_neo_client(_do)

    async def sync_neo_release(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        logger.info("[Neo] POST /skills/neo/sync requested.")
        data = await request.get_json()
        release_id = data.get("release_id")
        skill_key = data.get("skill_key")
        require_stable = _to_bool(data.get("require_stable"), True)
        if not release_id and not skill_key:
            return Response().error("Missing release_id or skill_key").__dict__

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
            return (
                Response()
                .ok(
                    {
                        "skill_key": result.skill_key,
                        "local_skill_name": result.local_skill_name,
                        "release_id": result.release_id,
                        "candidate_id": result.candidate_id,
                        "payload_ref": result.payload_ref,
                        "map_path": result.map_path,
                        "synced_at": result.synced_at,
                    }
                )
                .__dict__
            )

        return await self._with_neo_client(_do)

    async def delete_neo_candidate(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        logger.info("[Neo] POST /skills/neo/delete-candidate requested.")
        data = await request.get_json()
        candidate_id = data.get("candidate_id")
        reason = data.get("reason")
        if not candidate_id:
            return Response().error("Missing candidate_id").__dict__

        async def _do(client):
            result = await self._delete_neo_candidate(client, candidate_id, reason)
            logger.info(f"[Neo] Candidate deleted: id={candidate_id}")
            return Response().ok(_to_jsonable(result)).__dict__

        return await self._with_neo_client(_do)

    async def delete_neo_release(self):
        if DEMO_MODE:
            return (
                Response()
                .error("You are not permitted to do this operation in demo mode")
                .__dict__
            )
        logger.info("[Neo] POST /skills/neo/delete-release requested.")
        data = await request.get_json()
        release_id = data.get("release_id")
        reason = data.get("reason")
        if not release_id:
            return Response().error("Missing release_id").__dict__

        async def _do(client):
            result = await self._delete_neo_release(client, release_id, reason)
            logger.info(f"[Neo] Release deleted: id={release_id}")
            return Response().ok(_to_jsonable(result)).__dict__

        return await self._with_neo_client(_do)
