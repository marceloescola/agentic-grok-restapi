from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import List, Set

from tools.base import ToolDef


SENSITIVE_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\.env", re.IGNORECASE),
    re.compile(r"\.pem$", re.IGNORECASE),
    re.compile(r"\.key$", re.IGNORECASE),
    re.compile(r"\.cert$", re.IGNORECASE),
    re.compile(r"credentials", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
]

ALLOWED_EXTENSIONS: Set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt", ".scala",
    ".md", ".rst", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".xml", ".html", ".css", ".scss",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat",
    ".sql", ".r", ".m", ".mm",
    ".dockerfile", ".patch", ".diff",
}

MAX_LINES: int = 2000
_MAX_FILE_SIZE: int = 512 * 1024  # 512KB
_DEFAULT_ALLOWED: str = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _is_sensitive(filename: str) -> bool:
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(filename):
            return True
    return False


def _is_binary(filepath: str) -> bool:
    mime: str | None
    mime, _ = mimetypes.guess_type(filepath)
    if mime is not None:
        if mime.startswith("text/"):
            return False
        if mime in ("application/json", "application/xml", "application/yaml"):
            return False
        if not mime.startswith("application/"):
            return True
    try:
        with open(filepath, "rb") as f:
            chunk: bytes = f.read(8192)
        return b"\0" in chunk
    except OSError:
        return True


def _is_allowed_extension(filepath: str) -> bool:
    ext: str = os.path.splitext(filepath)[1].lower()
    return ext in ALLOWED_EXTENSIONS


_ALLOWED_DIRS: List[str] = []


def set_allowed_dirs(dirs: List[str]) -> None:
    global _ALLOWED_DIRS
    resolved: List[str] = []
    for d in dirs:
        p: str = os.path.realpath(d)
        if os.path.isdir(p):
            resolved.append(p)
    _ALLOWED_DIRS[:] = resolved


def _check_path(requested: str) -> str:
    if not _ALLOWED_DIRS:
        set_allowed_dirs([_DEFAULT_ALLOWED])

    raw: str = os.path.expanduser(requested)
    if not os.path.isabs(raw):
        raw = os.path.join(_DEFAULT_ALLOWED, raw)

    resolved: str = os.path.realpath(raw)

    if not os.path.exists(resolved):
        raise PermissionError(f"Path not found: {requested}")

    if not resolved.startswith(tuple(_ALLOWED_DIRS)):
        raise PermissionError(
            f"Access denied: '{requested}' is outside allowed directories. "
            f"Allowed: {', '.join(_ALLOWED_DIRS)}"
        )

    if not os.path.isfile(resolved):
        raise PermissionError(f"Not a file: {requested}")

    return resolved


class FileReadTool:
    @property
    def definition(self) -> ToolDef:
        return ToolDef(
            name="file_read",
            description=(
                "Read the contents of a text file from the local filesystem. "
                "Returns up to 2000 lines at a time. Use offset=N to read more."
            ),
            parameters={
                "path": "Relative or absolute path to the file",
                "offset": "Starting line number (1-indexed, default 1)",
                "limit": "Maximum lines to return (max 2000, default 2000)",
            },
        )

    async def run(self, path: str = "", offset: str = "1", limit: str = "2000") -> str:
        if not path.strip():
            return "Error: path is required"

        try:
            resolved: str = _check_path(path.strip())
        except PermissionError as exc:
            return f"Error: {exc}"

        basename: str = os.path.basename(resolved)
        if _is_sensitive(basename):
            return "Error: Cannot read sensitive files (secrets, credentials, keys, .env)"
        if _is_binary(resolved):
            return f"Error: '{path}' is a binary file"
        if not _is_allowed_extension(resolved):
            return (
                f"Error: Unsupported file type for '{path}'. "
                f"Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        file_size: int = os.path.getsize(resolved)
        if file_size > _MAX_FILE_SIZE:
            return (
                f"Error: File too large ({file_size} bytes, max {_MAX_FILE_SIZE}). "
                f"Try a smaller file."
            )

        try:
            start: int = max(1, int(offset))
        except (ValueError, TypeError):
            start = 1
        try:
            rows: int = max(1, min(MAX_LINES, int(limit)))
        except (ValueError, TypeError):
            rows = MAX_LINES

        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                all_lines: List[str] = f.readlines()
        except OSError as exc:
            return f"Error: Cannot read file: {exc}"

        total: int = len(all_lines)
        if start > total:
            return f"Error: Offset {start} exceeds file length ({total} lines)"

        chunk: List[str] = all_lines[start - 1 : start - 1 + rows]
        last_line: int = start - 1 + len(chunk)
        content: str = "".join(chunk)
        truncated: bool = last_line < total

        header: str = f"--- {path} (lines {start}-{last_line}/{total}) ---\n"
        footer: str = ""
        if truncated:
            footer = f"\n--- truncated at line {last_line}/{total}, use offset={last_line + 1} to continue ---"

        return header + content + footer
