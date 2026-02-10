import asyncio
import json
import os
import re
import ssl
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
import certifi
from quart import request

from astrbot.core import DEMO_MODE, logger
from astrbot.core.skills.skill_manager import SkillManager
from astrbot.core.utils.astrbot_path import (
    get_astrbot_data_path,
    get_astrbot_temp_path,
)

from .route import Response, Route, RouteContext

SKILLS_HOT_CACHE_TTL_SECONDS = 15 * 60
SKILLS_SEARCH_API_URL = "https://skills.sh/api/search"

SKILLS_VIEW_TO_PATH = {
    "hot": "/hot",
    "trending": "/trending",
    "all": "/",
}

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


class SkillsRoute(Route):
    def __init__(self, context: RouteContext, core_lifecycle) -> None:
        super().__init__(context)
        self.core_lifecycle = core_lifecycle
        self.routes = {
            "/skills": ("GET", self.get_skills),
            "/skills/detail": ("GET", self.get_skill_detail),
            "/skills/file": ("GET", self.get_file_content),
            "/skills/hot": ("GET", self.get_hot_skills),
            "/skills/search": ("GET", self.search_skills),
            "/skills/install": ("POST", self.install_skill),
            "/skills/upload": ("POST", self.upload_skill),
            "/skills/update": ("POST", self.update_skill),
            "/skills/update_detail": ("POST", self.update_skill_detail),
            "/skills/delete": ("POST", self.delete_skill),
        }
        self.register_routes()

    async def get_skills(self):
        try:
            provider_settings = self.core_lifecycle.astrbot_config.get(
                "provider_settings", {}
            )
            runtime = provider_settings.get("computer_use_runtime", "local")
            skills = SkillManager().list_skills(
                active_only=False, runtime=runtime, show_sandbox_path=False
            )
            return (
                Response()
                .ok(
                    {
                        "skills": [skill.__dict__ for skill in skills],
                    }
                )
                .__dict__
            )
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def get_hot_skills(self):
        force_refresh = request.args.get("force_refresh", "false").lower() == "true"
        limit_param = request.args.get("limit", "200")
        view_param = str(
            request.args.get("view", request.args.get("mode", "hot")) or "hot"
        ).strip()
        view = self._normalize_view(view_param)
        if not view:
            return Response().error("Invalid view value").__dict__
        try:
            limit = max(1, min(int(limit_param), 1000))
        except ValueError:
            return Response().error("Invalid limit value").__dict__

        try:
            data = await self._get_skills_view_data(
                view=view, force_refresh=force_refresh
            )
            skills = data.get("skills", [])
            payload = {
                "skills": skills[:limit],
                "totalSkills": data.get("totalSkills", len(skills)),
                "allTimeTotal": data.get("allTimeTotal", 0),
                "view": data.get("view", view),
            }
            return Response().ok(payload).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def search_skills(self):
        q = str(request.args.get("q", "") or "").strip()
        if len(q) < 2:
            return Response().error("Query must be at least 2 characters").__dict__
        limit_param = request.args.get("limit", "50")
        try:
            limit = max(1, min(int(limit_param), 100))
        except ValueError:
            return Response().error("Invalid limit value").__dict__
        try:
            data = await self._search_skills_api(query=q, limit=limit)
            return Response().ok(data).__dict__
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
            proxy = self._normalize_proxy_value(data.get("proxy", ""))

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

            temp_dir = Path(get_astrbot_temp_path())
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = str(temp_dir / filename)
            await file.save(temp_path)

            logger.info(f"Uploading skill from file: {filename}")
            skill_mgr = SkillManager()
            skill_name = skill_mgr.install_skill_from_zip(temp_path, overwrite=True)
            logger.info(f"Skill uploaded successfully: {skill_name}")

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
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except Exception:
                    logger.warning(f"Failed to remove temp skill file: {temp_path}")

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
            logger.info(f"Skill deleted successfully: {name}")
            return Response().ok({"name": name}).__dict__
        except Exception as e:
            logger.error(f"Failed to delete skill: {e}")
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    def _normalize_view(self, view: str) -> str | None:
        normalized = view.lower().strip()
        if normalized in SKILLS_VIEW_TO_PATH:
            return normalized
        if normalized in {"all-time", "all_time"}:
            return "all"
        if normalized in {"24h", "trend24h", "trending-24h"}:
            return "trending"
        return None

    def _get_hot_cache_path(self, view: str) -> str:
        return str(Path(get_astrbot_data_path()) / f"skills_{view}_cache.json")

    def _load_hot_cache(self, view: str) -> dict[str, Any] | None:
        cache_path = self._get_hot_cache_path(view)
        if not Path(cache_path).exists():
            return None
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            timestamp = cache.get("timestamp")
            data = cache.get("data")
            if not isinstance(timestamp, (int, float)) or not isinstance(data, dict):
                return None
            return {"timestamp": int(timestamp), "data": data}
        except Exception:
            logger.warning("Failed to load skills hot cache.")
            return None

    def _save_hot_cache(self, view: str, data: dict[str, Any]) -> None:
        cache_path = self._get_hot_cache_path(view)
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": int(time.time()),
            "data": data,
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    async def _get_skills_view_data(
        self,
        *,
        view: str,
        force_refresh: bool,
    ) -> dict[str, Any]:
        cached = self._load_hot_cache(view)
        now = int(time.time())
        if (
            not force_refresh
            and cached
            and now - cached["timestamp"] <= SKILLS_HOT_CACHE_TTL_SECONDS
        ):
            return cached["data"]

        try:
            fresh = await self._fetch_skills_view(view=view)
            self._save_hot_cache(view, fresh)
            return fresh
        except Exception as e:
            if cached:
                logger.warning(
                    f"Failed to fetch {view} skills from skills.sh, using cache."
                )
                return cached["data"]
            raise RuntimeError(f"Failed to fetch {view} skills from skills.sh") from e

    async def _fetch_skills_view(self, *, view: str) -> dict[str, Any]:
        route_path = SKILLS_VIEW_TO_PATH.get(view)
        if not route_path:
            raise ValueError("Unsupported skills view.")
        if route_path == "/":
            url = "https://skills.sh/"
        else:
            url = f"https://skills.sh{route_path}"
        headers = {
            "RSC": "1",
            "User-Agent": "AstrBot/SkillsFetcher",
        }
        timeout = aiohttp.ClientTimeout(total=30)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=timeout,
            connector=connector,
        ) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"skills.sh {view} list request failed: HTTP {response.status}"
                    )
                payload = await response.text()
        return self._parse_hot_skills_payload(payload, fallback_view=view)

    async def _search_skills_api(self, *, query: str, limit: int) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=30)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        params = {
            "q": query,
            "limit": str(limit),
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": "AstrBot/SkillsFetcher",
        }
        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=timeout,
            connector=connector,
        ) as session:
            async with session.get(
                SKILLS_SEARCH_API_URL, params=params, headers=headers
            ) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"skills.sh search request failed: HTTP {response.status}"
                    )
                raw = await response.json()

        raw_skills = raw.get("skills", []) if isinstance(raw, dict) else []
        skills: list[dict[str, Any]] = []
        for item in raw_skills:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            skill_id = str(item.get("skillId", "")).strip()
            skill_path = str(item.get("id", "")).strip()
            if not source and "/" in skill_path:
                source = "/".join(skill_path.split("/")[:2]).strip()
            if not skill_id and "/" in skill_path:
                skill_id = skill_path.split("/")[-1].strip()
            if not source or not skill_id:
                continue
            skills.append(
                {
                    "source": source,
                    "skillId": skill_id,
                    "name": str(item.get("name", "")).strip() or skill_id,
                    "installs": int(item.get("installs", 0) or 0),
                }
            )

        return {
            "query": query,
            "view": "search",
            "skills": skills,
            "totalSkills": len(skills),
            "allTimeTotal": 0,
        }

    def _parse_hot_skills_payload(
        self,
        payload: str,
        *,
        fallback_view: str = "hot",
    ) -> dict[str, Any]:
        json_blob = None
        for line in payload.splitlines():
            if line.startswith("a:[") and "initialSkills" in line:
                json_blob = line[2:]
                break
        if not json_blob:
            for line in payload.splitlines():
                if line.startswith("a:["):
                    json_blob = line[2:]
                    break
        if not json_blob:
            raise ValueError("Unable to parse hot skills payload.")

        parsed = json.loads(json_blob)
        if (
            not isinstance(parsed, list)
            or len(parsed) < 4
            or not isinstance(parsed[3], dict)
        ):
            raise ValueError("Unexpected hot skills payload structure.")

        meta = parsed[3]
        raw_skills = meta.get("initialSkills", [])
        skills: list[dict[str, Any]] = []
        for item in raw_skills:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            skill_id = str(item.get("skillId", "")).strip()
            if not source or not skill_id:
                continue
            skills.append(
                {
                    "source": source,
                    "skillId": skill_id,
                    "name": str(item.get("name", "")).strip() or skill_id,
                    "installs": int(item.get("installs", 0) or 0),
                    "installsYesterday": int(item.get("installsYesterday", 0) or 0),
                    "change": int(item.get("change", 0) or 0),
                }
            )

        return {
            "skills": skills,
            "totalSkills": int(meta.get("totalSkills", len(skills)) or len(skills)),
            "allTimeTotal": int(meta.get("allTimeTotal", 0) or 0),
            "view": str(meta.get("view", fallback_view) or fallback_view),
        }

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
                if temp_path and Path(temp_path).exists():
                    try:
                        Path(temp_path).unlink()
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
                            Path(get_astrbot_temp_path()).mkdir(
                                parents=True, exist_ok=True
                            )
                            fd, archive_path = tempfile.mkstemp(
                                prefix=f"{repo}-",
                                suffix=".zip",
                                dir=get_astrbot_temp_path(),
                            )
                            os.close(fd)
                            with open(archive_path, "wb") as f:
                                async for chunk in response.content.iter_chunked(
                                    64 * 1024
                                ):
                                    f.write(chunk)
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
        if not _validate_file_extension(file_path):
            return Response().error("File type not allowed for editing").__dict__
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
            with open(full_path, encoding="utf-8") as f:
                content = f.read()
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
            if not _validate_file_extension(file_path):
                return Response().error("File type not allowed for editing").__dict__
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
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Skill file updated: {name}/{file_path}")
            return Response().ok({"name": name, "file_path": file_path}).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__
