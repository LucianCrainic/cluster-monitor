"""Read-only remote filesystem request and response models."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from cluster_monitor.models.base import ApiModel


class RemoteDirectoryRequest(ApiModel):
    path: str | None = None
    show_hidden: bool = False


class RemoteFilePreviewRequest(ApiModel):
    path: str


class RemoteFileKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


class RemotePreviewStatus(StrEnum):
    AVAILABLE = "available"
    BINARY = "binary"
    TOO_LARGE = "too_large"
    SPECIAL = "special"


class RemoteFileEntry(ApiModel):
    name: str
    path: str
    kind: RemoteFileKind
    size_bytes: int = Field(ge=0)
    modified_at: datetime
    permissions: str
    readable: bool
    symlink_target: str | None = None
    target_kind: RemoteFileKind | None = None


class RemoteDirectory(ApiModel):
    cluster_id: str
    path: str
    parent_path: str | None
    entries: list[RemoteFileEntry]
    truncated: bool = False


class RemoteFilePreview(ApiModel):
    cluster_id: str
    path: str
    name: str
    kind: RemoteFileKind
    size_bytes: int = Field(ge=0)
    modified_at: datetime
    permissions: str
    symlink_target: str | None = None
    status: RemotePreviewStatus
    content: str | None = None
    language: str | None = None
