from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from cluster_monitor.connection import build_remote_command
from cluster_monitor.exceptions import (
    RemotePathForbiddenError,
    RemotePathInvalidError,
    RemotePathNotFoundError,
)
from cluster_monitor.models import (
    RemoteDirectoryRequest,
    RemoteFilePreviewRequest,
    RemotePreviewStatus,
)
from cluster_monitor.slurm.commands import build_remote_files_command
from cluster_monitor.slurm.remote_files import (
    parse_remote_directory,
    parse_remote_file_preview,
    validate_remote_path,
)


def _run_helper(action: str, path: Path, *, hidden: bool = False) -> str:
    command = build_remote_files_command(action, str(path), show_hidden=hidden)
    completed = subprocess.run(
        [command.executable, *command.arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_remote_path_is_one_quoted_ssh_argument() -> None:
    path = "/home/researcher/a b;$(touch nope)/résumé.txt"
    command = build_remote_files_command("preview", path)

    assert command.executable == "python3"
    assert command.arguments[-3:] == ("preview", path, "0")
    assert build_remote_command(command.executable, command.arguments).endswith(
        "preview '/home/researcher/a b;$(touch nope)/résumé.txt' 0"
    )
    assert path not in command.arguments[2]


def test_directory_helper_sorts_hides_and_limits_metadata(tmp_path: Path) -> None:
    (tmp_path / "z-dir").mkdir()
    (tmp_path / "a file.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".secret").write_text("hidden", encoding="utf-8")
    (tmp_path / "link").symlink_to(tmp_path / "a file.txt")

    visible = parse_remote_directory(_run_helper("list", tmp_path), "test")
    hidden = parse_remote_directory(_run_helper("list", tmp_path, hidden=True), "test")

    assert [entry.name for entry in visible.entries] == ["z-dir", "a file.txt", "link"]
    assert [entry.name for entry in hidden.entries] == [
        "z-dir",
        ".secret",
        "a file.txt",
        "link",
    ]
    assert visible.entries[-1].symlink_target == str(tmp_path / "a file.txt")
    assert visible.entries[-1].target_kind == "file"


def test_directory_helper_caps_large_directories(tmp_path: Path) -> None:
    for index in range(505):
        (tmp_path / f"file-{index:03}.txt").touch()

    directory = parse_remote_directory(_run_helper("list", tmp_path), "test")

    assert len(directory.entries) == 500
    assert directory.truncated is True


def test_preview_helper_distinguishes_text_binary_and_oversized(tmp_path: Path) -> None:
    text_file = tmp_path / "job.sh"
    text_file.write_text("#!/bin/bash\necho hello\n", encoding="utf-8")
    binary_file = tmp_path / "data.bin"
    binary_file.write_bytes(b"\x00\xff")
    invalid_utf8_file = tmp_path / "invalid.txt"
    invalid_utf8_file.write_bytes(b"plain\xfftext")
    large_file = tmp_path / "large.txt"
    large_file.write_bytes(b"x" * (1024 * 1024 + 1))

    text_preview = parse_remote_file_preview(_run_helper("preview", text_file), "test")
    binary_preview = parse_remote_file_preview(_run_helper("preview", binary_file), "test")
    invalid_preview = parse_remote_file_preview(_run_helper("preview", invalid_utf8_file), "test")
    large_preview = parse_remote_file_preview(_run_helper("preview", large_file), "test")

    assert text_preview.status is RemotePreviewStatus.AVAILABLE
    assert text_preview.content == "#!/bin/bash\necho hello\n"
    assert text_preview.language == "shell"
    assert binary_preview.status is RemotePreviewStatus.BINARY
    assert binary_preview.content is None
    assert invalid_preview.status is RemotePreviewStatus.BINARY
    assert large_preview.status is RemotePreviewStatus.TOO_LARGE
    assert large_preview.content is None


def test_preview_helper_never_reads_directories_or_fifos(tmp_path: Path) -> None:
    directory_preview = parse_remote_file_preview(_run_helper("preview", tmp_path), "test")
    fifo = tmp_path / "events.fifo"
    fifo_path = str(fifo)
    os.mkfifo(fifo_path)
    fifo_preview = parse_remote_file_preview(_run_helper("preview", fifo), "test")

    assert directory_preview.status is RemotePreviewStatus.SPECIAL
    assert fifo_preview.status is RemotePreviewStatus.SPECIAL


def test_helper_errors_are_safe_and_structured() -> None:
    with pytest.raises(RemotePathNotFoundError):
        parse_remote_directory(json.dumps({"error": "not_found"}), "test")
    with pytest.raises(RemotePathForbiddenError):
        parse_remote_file_preview(json.dumps({"error": "forbidden"}), "test")


@pytest.mark.parametrize("path", ["relative/file", "/bad\x00path", "/" + "a" * 4097])
def test_request_models_reject_invalid_paths(path: str) -> None:
    request = RemoteFilePreviewRequest(path=path)
    with pytest.raises(RemotePathInvalidError):
        validate_remote_path(
            request.path,
            "test",
            allow_login_directory=False,
        )

    if path.startswith("/"):
        directory = RemoteDirectoryRequest(path=path)
        with pytest.raises(RemotePathInvalidError):
            validate_remote_path(
                directory.path,
                "test",
                allow_login_directory=True,
            )
