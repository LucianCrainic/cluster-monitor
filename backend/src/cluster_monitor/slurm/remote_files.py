"""Safe parsing for the static read-only remote file helper."""

from __future__ import annotations

import base64
import json
from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from cluster_monitor.exceptions import (
    RemotePathForbiddenError,
    RemotePathInvalidError,
    RemotePathNotFoundError,
)
from cluster_monitor.models import RemoteDirectory, RemoteFilePreview


class RemoteFileResponseError(ValueError):
    """The remote helper returned a response that could not be normalized."""


def validate_remote_path(
    path: str | None,
    cluster_id: str,
    *,
    allow_login_directory: bool,
) -> None:
    if path is None and allow_login_directory:
        return
    if (
        path is None
        or not path.startswith("/")
        or "\x00" in path
        or len(path.encode("utf-8")) > 4096
    ):
        raise RemotePathInvalidError(cluster_id)


def parse_remote_directory(output: str, cluster_id: str) -> RemoteDirectory:
    payload = _payload(output, cluster_id)
    try:
        return RemoteDirectory.model_validate(
            {
                "cluster_id": cluster_id,
                "path": payload["path"],
                "parent_path": payload.get("parent_path"),
                "entries": payload.get("entries", []),
                "truncated": payload.get("truncated", False),
            }
        )
    except (KeyError, ValidationError, TypeError):
        raise RemoteFileResponseError("The remote directory response is invalid.") from None


def parse_remote_file_preview(output: str, cluster_id: str) -> RemoteFilePreview:
    payload = _payload(output, cluster_id)
    encoded = payload.pop("content_base64", None)
    if encoded is not None:
        if not isinstance(encoded, str):
            raise RemoteFileResponseError("The remote file response is invalid.")
        try:
            raw = base64.b64decode(encoded, validate=True)
            content = raw.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError):
            raise RemoteFileResponseError("The remote file response is invalid.") from None
        payload["content"] = content
    payload["cluster_id"] = cluster_id
    payload["language"] = _language_for_path(
        str(payload.get("path", "")),
        payload.get("content") if isinstance(payload.get("content"), str) else None,
    )
    try:
        return RemoteFilePreview.model_validate(payload)
    except ValidationError:
        raise RemoteFileResponseError("The remote file response is invalid.") from None


def _payload(output: str, cluster_id: str) -> dict[str, Any]:
    try:
        decoded: object = json.loads(output)
    except json.JSONDecodeError:
        raise RemoteFileResponseError("The remote file response is not valid JSON.") from None
    if not isinstance(decoded, dict):
        raise RemoteFileResponseError("The remote file response is invalid.")
    payload = dict(decoded)
    error = payload.get("error")
    if error is not None:
        if error == "not_found":
            raise RemotePathNotFoundError(cluster_id)
        if error == "forbidden":
            raise RemotePathForbiddenError(cluster_id)
        if error == "not_directory":
            raise RemotePathInvalidError(cluster_id, "The remote path is not a directory.")
        if error == "invalid_path":
            raise RemotePathInvalidError(cluster_id)
        raise RemoteFileResponseError("The remote file helper could not complete the request.")
    return payload


def _language_for_path(path: str, content: str | None = None) -> str:
    parsed = PurePosixPath(path)
    name = parsed.name.casefold()
    if name in {"dockerfile", "containerfile"}:
        return "dockerfile"

    suffix = parsed.suffix.casefold()
    language = {
        ".bash": "shell",
        ".cjs": "javascript",
        ".c": "c",
        ".cc": "cpp",
        ".cfg": "properties",
        ".conf": "properties",
        ".cpp": "cpp",
        ".css": "css",
        ".diff": "diff",
        ".dockerfile": "dockerfile",
        ".env": "shell",
        ".err": "text",
        ".h": "c",
        ".hpp": "cpp",
        ".html": "html",
        ".ini": "properties",
        ".ipynb": "json",
        ".js": "javascript",
        ".jsx": "javascript",
        ".json": "json",
        ".log": "text",
        ".md": "markdown",
        ".mjs": "javascript",
        ".mts": "typescript",
        ".out": "text",
        ".patch": "diff",
        ".py": "python",
        ".properties": "properties",
        ".sbatch": "shell",
        ".sh": "shell",
        ".sql": "sql",
        ".slurm": "shell",
        ".toml": "toml",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".txt": "text",
        ".xml": "xml",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(suffix)
    if language is not None:
        return language

    first_line = content.partition("\n")[0].casefold() if content else ""
    if first_line.startswith("#!"):
        if "python" in first_line:
            return "python"
        if any(shell_name in first_line for shell_name in ("bash", "zsh", "ksh", "/sh")):
            return "shell"
    return "text"
