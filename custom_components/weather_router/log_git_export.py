"""Narrow GitHub writer for explicit WeatherRouter diagnostic snapshots."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import json
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from aiohttp import ClientSession

from .const import DEV_BUILD_VERSION, DEV_LOADER_REV, LOG_GIT_REPOSITORY, LOG_GIT_ROOT

_GITHUB_API = "https://api.github.com"
_API_VERSION = "2022-11-28"
_USER_AGENT = "WeatherRouter-Log-Export"
_ARCHIVE_REPOSITORY = "TheDaimos/Project-Log-And-Export"
_ARCHIVE_ROOT = "exports/weather-router"
_SECRET_KEY_RE = re.compile(
    r"(?i)(token|secret|password|passwd|authorization|cookie|api[_-]?key|credential|url|uri|latitude|longitude|coordinate|bbox)"
)
_ALWAYS_SECRET_KEY_RE = re.compile(
    r"(?i)(token|secret|password|passwd|authorization|cookie|api[_-]?key|credential|url|uri)"
)
_LOCATION_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:latitude|longitude|lat|lon|lng|coordinate|coordinates|bbox)(?:$|_)"
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE),
    re.compile(r"(?i)\bBearer\s+[^\s,;]+"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]+\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]+\b"),
)


class WeatherRouterLogExportError(RuntimeError):
    """Base failure for explicit WeatherRouter log export."""


def _sanitize(value: Any, secrets: tuple[str, ...] = (), *, allow_location: bool = False) -> Any:
    """Recursively redact secrets immediately before Git serialization."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY_RE.search(key_text) and not (allow_location and _LOCATION_KEY_RE.search(key_text) and not _ALWAYS_SECRET_KEY_RE.search(key_text)):
                result[key_text] = "<redacted>" if item not in (None, "", False) else item
            else:
                result[key_text] = _sanitize(item, secrets, allow_location=allow_location)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, secrets, allow_location=allow_location) for item in value]
    if isinstance(value, str):
        text = value
        for secret in secrets:
            if secret and len(secret) >= 6:
                text = text.replace(secret, "<redacted>")
        for pattern in _SECRET_TEXT_PATTERNS:
            text = pattern.sub("<redacted>", text)
        return text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize(repr(value), secrets, allow_location=allow_location)


def _snapshot_when(snapshot: dict[str, Any]) -> datetime:
    meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
    generated = str(
        snapshot.get("generated_at")
        or meta.get("completed_at")
        or meta.get("started_at")
        or ""
    )
    try:
        parsed = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def _archive_type(schema: str) -> str:
    if schema == "weather_router.routing_diagnostic.v1":
        return "routing-test"
    if "provider_diagnostics" in schema:
        return "provider"
    if schema == "weather_router.event_log.v1":
        return "logs"
    return "diagnostics"


def _archive_version(snapshot: dict[str, Any]) -> str:
    """Extract a real version or fall back to the running WeatherRouter build."""
    for raw in (snapshot.get("version"), snapshot.get("build")):
        match = re.search(r"\b\d+\.\d+\.\d+\b", str(raw or ""))
        if match:
            return match.group()
    return DEV_BUILD_VERSION


def _archive_test_id(snapshot: dict[str, Any]) -> str:
    meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
    test = snapshot.get("test") if isinstance(snapshot.get("test"), dict) else {}
    candidate = test.get("id") or snapshot.get("test_id") or meta.get("trace_id") or "untagged"
    if _metadata_text(candidate) is None:
        candidate = meta.get("trace_id") if _metadata_text(meta.get("trace_id")) else "untagged"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(candidate)).strip("-")[:72] or "untagged"



def _metadata_text(value: Any, secrets: tuple[str, ...] = ()) -> str | None:
    """Only bounded and secret-safe metadata may be indexed."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 180 or any(ord(c) < 32 for c in value):
        return None
    if _sanitize(value, secrets) != value or "<redacted>" in value.lower():
        return None
    return value


def _metadata_attempt(value: Any) -> int | None:
    return value if type(value) is int and 1 <= value <= 1_000_000 else None


def _metadata_counts(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict) or not value or len(value) > 20:
        return None
    result: dict[str, int] = {}
    for key, count in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][A-Za-z0-9_]{0,39}", key):
            return None
        if type(count) is not int or not 0 <= count <= 1_000_000_000:
            return None
        result[key] = count
    return result


_ARCHIVE_TEST_STATUSES = {
    "PASS", "FAIL", "SKIPPED", "ABORTED", "BLOCKED", "NOT_VALUABLE", "UNKNOWN",
}


def _export_path(
    snapshot: dict[str, Any], *, root: str = LOG_GIT_ROOT,
    archive: bool = False, export_id: str | None = None,
) -> str:
    when = _snapshot_when(snapshot)
    schema = str(snapshot.get("schema") or "")
    if archive:
        stamp = when.strftime("%Y-%m-%dT%H-%M-%SZ")
        filename = (
            f"{stamp}__weather-router__{_archive_version(snapshot)}__"
            f"{_archive_type(schema)}__{_archive_test_id(snapshot)}-{export_id or uuid4().hex}.json"
        )
        path = PurePosixPath(root) / when.strftime("%Y-%m") / _archive_type(schema) / filename
    else:
        label = snapshot.get("build")
        if not label and schema == "weather_router.all_provider_diagnostics.v1":
            label = "provider-diagnostics-all"
        elif not label and schema == "weather_router.provider_diagnostics.v1":
            provider = snapshot.get("provider")
            provider_id = provider.get("id") if isinstance(provider, dict) else None
            label = f"provider-diagnostics-{provider_id or 'single'}"
        elif not label and schema == "weather_router.routing_diagnostic.v1":
            request = snapshot.get("request")
            capability = request.get("capability") if isinstance(request, dict) else None
            label = f"routing-diagnostic-{capability or 'resolve'}"
        elif not label:
            label = "unknown"
        build = re.sub(r"[^A-Za-z0-9._-]+", "-", str(label)).strip("-")[:64]
        filename = f"{when.strftime('%Y%m%dT%H%M%SZ')}-wr-{build or 'unknown'}-{uuid4().hex[:8]}.json"
        path = PurePosixPath(root) / when.strftime("%Y-%m-%d") / filename
    normalized = path.as_posix()
    if ".." in path.parts or not normalized.startswith(f"{root}/"):
        raise WeatherRouterLogExportError("log export path escaped reserved root")
    return normalized


class WeatherRouterLogGitClient:
    """Create new sanitized WeatherRouter log files in one fixed repository."""

    def __init__(
        self, session: ClientSession, token: str, *,
        repository: str = _ARCHIVE_REPOSITORY,
        root: str = _ARCHIVE_ROOT,
        require_private: bool = True,
    ) -> None:
        if repository != _ARCHIVE_REPOSITORY or root != _ARCHIVE_ROOT or not require_private:
            raise WeatherRouterLogExportError(
                "Diagnostic exports are restricted to the isolated private archive"
            )
        token = token.strip()
        if not token:
            raise WeatherRouterLogExportError("GitHub write token is required")
        self._session = session
        self._token = token
        self._repository = repository
        self._root = root
        self._require_private = require_private

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": _USER_AGENT,
        }

    def _repo_url(self, suffix: str = "") -> str:
        owner, repo = self._repository.split("/", 1)
        return (
            f"{_GITHUB_API}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
            f"{suffix}"
        )

    async def async_repository(self) -> dict[str, Any]:
        """Verify access and return safe repository metadata."""
        async with self._session.get(
            self._repo_url(),
            headers=self._headers(),
        ) as response:
            if response.status == 401:
                raise WeatherRouterLogExportError("GitHub authentication failed")
            if response.status == 403:
                raise WeatherRouterLogExportError("GitHub repository access forbidden")
            if response.status == 404:
                raise WeatherRouterLogExportError("WeatherRouter repository not found")
            if response.status >= 400:
                raise WeatherRouterLogExportError(
                    f"GitHub returned HTTP {response.status}"
                )
            payload = await response.json()

        if not isinstance(payload, dict):
            raise WeatherRouterLogExportError("invalid GitHub repository response")
        default_branch = payload.get("default_branch")
        full_name = payload.get("full_name")
        if not isinstance(default_branch, str) or not default_branch:
            raise WeatherRouterLogExportError("GitHub default branch missing")
        if full_name != self._repository:
            raise WeatherRouterLogExportError("unexpected GitHub repository identity")
        if self._require_private and not payload.get("private"):
            raise WeatherRouterLogExportError("Log&Export repository must remain private")
        permissions = payload.get("permissions")
        if isinstance(permissions, dict) and permissions.get("push") is False:
            raise WeatherRouterLogExportError("GitHub token has no repository write permission")
        return {
            "repository": full_name,
            "default_branch": default_branch,
            "private": bool(payload.get("private", False)),
        }

    async def async_export(
        self,
        snapshot: dict[str, Any],
        *,
        branch: str,
    ) -> dict[str, Any]:
        """Create one new JSON log snapshot; never overwrite an existing file."""
        export_id = uuid4().hex
        path = _export_path(
            snapshot, root=self._root, archive=self._require_private, export_id=export_id,
        )
        safe_snapshot = _sanitize(
            snapshot, (self._token,), allow_location=self._require_private,
        )
        payload = {
            "schema": "weather_router.git_log_export.v1",
            "repository": self._repository,
            "branch": branch,
            "path": path,
            "exported_at": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "log": safe_snapshot,
        }
        if self._require_private:
            request = snapshot.get("request") if isinstance(snapshot.get("request"), dict) else {}
            test = snapshot.get("test") if isinstance(snapshot.get("test"), dict) else {}
            meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
            scope = snapshot.get("scope") if isinstance(snapshot.get("scope"), dict) else {}
            safe = lambda value: _metadata_text(value, (self._token,))
            case_id = safe(test.get("caseId") or test.get("case_id") or test.get("id") or snapshot.get("test_id"))
            run_id = safe(test.get("runId") or test.get("run_id") or meta.get("trace_id"))
            test_status = safe(test.get("status"))
            if test_status not in _ARCHIVE_TEST_STATUSES:
                test_status = None
            metadata = {
                "exportSchema": "daimos-project-log-export-v1",
                "application": {
                    "id": "weather-router",
                    "name": "WeatherRouter",
                    "version": _archive_version(snapshot),
                    "build": safe(snapshot.get("build")),
                    "loader": DEV_LOADER_REV,
                    "instanceId": None,
                },
                "export": {
                    "type": _archive_type(str(snapshot.get("schema") or "")),
                    "capturedAt": _snapshot_when(snapshot).isoformat().replace("+00:00", "Z"),
                    "exportedAt": payload["exported_at"],
                    "exportId": export_id,
                },
                "source": {
                    "repository": "TheDaimos/weather-router-dev",
                    "commit": None,
                },
                "test": {
                    "id": safe(test.get("id") or snapshot.get("test_id")),
                    "caseId": case_id,
                    "runId": run_id,
                    "attempt": _metadata_attempt(test.get("attempt")),
                    "planStep": safe(test.get("planStep") or test.get("plan_step")),
                    "status": test_status,
                    "capabilityId": safe(
                        test.get("capabilityId") or request.get("capability") or scope.get("capability")
                    ),
                    "capabilityUiNumber": safe(
                        test.get("capabilityUiNumber") or request.get("capability_ui_number")
                    ),
                    "counts": _metadata_counts(test.get("counts")),
                },
            }
            payload.update(metadata)
            payload["metadata"] = metadata

        raw = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        content = base64.b64encode(raw).decode("ascii")
        safe_path = "/".join(quote(part, safe="") for part in path.split("/"))

        async with self._session.put(
            self._repo_url(f"/contents/{safe_path}"),
            headers=self._headers(),
            json={
                "message": "chore(logs): export WeatherRouter diagnostic log [skip ci]",
                "content": content,
                "branch": branch,
            },
        ) as response:
            if response.status == 401:
                raise WeatherRouterLogExportError("GitHub authentication failed")
            if response.status == 403:
                raise WeatherRouterLogExportError("GitHub write access forbidden")
            if response.status == 422:
                raise WeatherRouterLogExportError("GitHub rejected log export")
            if response.status >= 400:
                raise WeatherRouterLogExportError(
                    f"GitHub log export returned HTTP {response.status}"
                )
            result = await response.json()

        commit = result.get("commit") if isinstance(result, dict) else None
        file_info = result.get("content") if isinstance(result, dict) else None
        commit_sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(commit_sha, str) or not commit_sha:
            raise WeatherRouterLogExportError("GitHub commit SHA missing")

        return {
            "repository": self._repository,
            "branch": branch,
            "path": path,
            "commit_sha": commit_sha,
            "commit_url": commit.get("html_url") if isinstance(commit, dict) else None,
            "file_url": file_info.get("html_url") if isinstance(file_info, dict) else None,
        }
