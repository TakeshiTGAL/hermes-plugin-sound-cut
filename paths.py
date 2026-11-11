"""Absolute paths that do not follow a symlink.

``..`` and ``.`` components are refused. The caller passes a lexical
absolute path. Output files are created with ``O_EXCL`` and ``O_NOFOLLOW``.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_CREATE_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC


class PathRefused(Exception):
    def __init__(self, kind: str, detail: str, errno_name: str = ""):
        self.kind = kind
        self.detail = detail
        self.errno_name = errno_name
        super().__init__(f"{kind}: {detail}")


def _errname(err: int) -> str:
    return errno.errorcode.get(err, "")


def _errno_kind(err: int, *, writing: bool) -> str:
    """Classify an open failure. A symlink is only ELOOP, never a permission or space error."""
    if err in (errno.EACCES, errno.EPERM):
        return "not_writable" if writing else "not_readable"
    if err == errno.EROFS:
        return "read_only"
    if err in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
        return "no_space"
    if err == errno.ENAMETOOLONG:
        return "bad_name"
    if err == errno.ENOTDIR:
        return "not_a_directory"
    if err == errno.EISDIR:
        return "not_a_file"
    if err == errno.ELOOP:
        return "symlink"
    if err == errno.EEXIST:
        return "exists"
    if err == errno.ENOENT:
        return "missing"
    return "io_error"


def symlink_next(*, wrote: bool) -> str:
    """Name a spelled directory only when it points somewhere else.

    When ``/tmp`` is already the regular directory, the sentence does not
    tell the caller to pass ``/tmp`` instead of ``/tmp``.
    """
    kept = "Nothing was written." if wrote else "Nothing was read through the link."
    hints = []
    tmp_target = os.path.realpath("/tmp")
    var_target = os.path.realpath("/var")
    if tmp_target != "/tmp":
        hints.append(f"{tmp_target} instead of /tmp")
    if var_target != "/var":
        hints.append(f"{var_target} instead of /var")
    lead = ("On macOS, pass " + " and ".join(hints) + ". ") if hints else ""
    return lead + "Pass the regular path, not the symlink. " + kept


def refusal_text(exc: PathRefused, *, surface: str, field: str = "") -> tuple[str, str, str]:
    """One table from a path refusal to the code, error, and next step.

    ``surface`` is ``read``, ``midi``, ``write`` (the plan), or ``create``
    (the exclusive open after approval). Lexical refusals stay ``outside``.
    Permission, read-only, and space errors keep their own codes.
    """
    kind = exc.kind
    writing = surface in {"write", "create"}
    kept = " Nothing was written." if writing else ""
    if kind == "symlink":
        if surface == "write":
            error = "A path component is a symlink, so it was not followed."
        elif surface == "create":
            error = "The output path is a symlink, so ffmpeg was not started."
        else:
            error = "The path is a symlink, so it was not followed."
        return "symlink", error, symlink_next(wrote=writing)
    if kind == "missing":
        if surface == "midi":
            return (
                "missing",
                "The path is not a file.",
                "Pass an existing MIDI file. This is not a claim about other folders.",
            )
        if writing:
            error = (
                "The input path is not a file."
                if field == "input_path"
                else "The output directory does not exist."
            )
            return "missing", error, "Create the directory or pass an existing file. Nothing was written."
        return (
            "missing",
            "The path is not a file.",
            "Pass an existing file. This is not a claim about other folders.",
        )
    if kind == "bad_path":
        return (
            "bad_argument",
            "The path contains a quote, a backtick, or a control character.",
            "Pass a plain absolute path." + kept,
        )
    if kind == "not_a_file":
        return (
            "not_a_file",
            "The path is not a regular file.",
            "Pass a file, not a directory." + kept,
        )
    if kind == "not_a_directory":
        if writing:
            return (
                "not_a_directory",
                "output_dir is not a directory.",
                "Pass a directory. Nothing was written.",
            )
        return "not_a_directory", "The path is not a directory.", "Pass a directory."
    if kind == "not_writable":
        return (
            "not_writable",
            "The directory is not writable, so the file was not created.",
            "Choose a directory you can write, or change its permissions. Nothing was written.",
        )
    if kind == "not_readable":
        if writing:
            return (
                "not_readable",
                "The path cannot be opened, so nothing was written.",
                "Choose a directory you can open and write. Nothing was written.",
            )
        return (
            "not_readable",
            "The path cannot be read, so nothing was measured.",
            "Choose a file you can read. Nothing was measured.",
        )
    if kind == "read_only":
        if writing:
            return (
                "read_only",
                "The filesystem is read-only, so the file was not created.",
                "Choose a directory on a writable filesystem. Nothing was written.",
            )
        return (
            "read_only",
            "The filesystem is read-only, so the path was not opened.",
            "Choose a path on a filesystem you can read. Nothing was measured.",
        )
    if kind == "no_space":
        if writing:
            return (
                "no_space",
                "The filesystem has no space left for the new file.",
                "Free some space or choose another directory. Nothing was written.",
            )
        return (
            "no_space",
            "The filesystem reported no space, so the path was not opened.",
            "Free some space and call again. Nothing was measured.",
        )
    if kind == "bad_name":
        return (
            "bad_argument",
            "The path is too long.",
            "Pass a shorter absolute path." + kept,
        )
    if kind == "exists":
        return (
            "exists",
            "The output already exists, so it was not overwritten.",
            "Pick another output_name. Nothing was written.",
        )
    if kind == "io_error":
        name = exc.errno_name or "OSError"
        tail = "Nothing was written." if writing else "Nothing was measured."
        return (
            "io_error",
            f"The path could not be opened ({name}).",
            f"Choose another absolute path. {tail}",
        )
    return (
        "outside",
        "The path must be absolute and must not contain . or .. components.",
        "Pass an absolute path with no . or .. component." + kept,
    )


def _close_all(fds: list[int]) -> None:
    for fd in reversed(fds):
        try:
            os.close(fd)
        except OSError:
            pass


def _open_child(parent_fd: int, name: str) -> tuple[int | None, str, int]:
    try:
        return os.open(name, _DIR_FLAGS, dir_fd=parent_fd), "", 0
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return None, "missing", exc.errno
        if exc.errno == errno.ELOOP:
            return None, "symlink", exc.errno
        try:
            info = os.lstat(name, dir_fd=parent_fd)
        except OSError as stat_exc:
            return None, _errno_kind(stat_exc.errno, writing=False), stat_exc.errno
        if stat.S_ISLNK(info.st_mode):
            return None, "symlink", exc.errno
        return None, _errno_kind(exc.errno, writing=False), exc.errno


def _parts(path: str) -> tuple[str, ...]:
    if not path or "\x00" in path or "\\" in path:
        raise PathRefused("outside", path or ".")
    if any(ord(ch) < 32 or ch in "`'\r" for ch in path):
        raise PathRefused("bad_path", path)
    raw = Path(path)
    if not raw.is_absolute():
        raise PathRefused("outside", path)
    parts = raw.parts
    if not parts or parts[0] != "/":
        raise PathRefused("outside", path)
    body = parts[1:]
    if any(part in ("", ".", "..") or "/" in part for part in body):
        raise PathRefused("outside", path)
    return body


def _bail(opened: list[int], kind: str, detail: str, err: int = 0) -> None:
    _close_all(opened)
    raise PathRefused(kind, detail, errno_name=_errname(err) if err else "")


def _walk(parts: tuple[str, ...]) -> tuple[list[int], str]:
    """Open each existing directory component. The last kind is for the tail."""
    opened: list[int] = []
    current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    opened.append(current)
    if not parts:
        return opened, "dir"
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        full = "/" + "/".join(parts)
        if last:
            try:
                info = os.lstat(part, dir_fd=current)
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    return opened, "missing"
                _bail(opened, _errno_kind(exc.errno, writing=False), full, exc.errno)
            if stat.S_ISLNK(info.st_mode):
                _bail(opened, "symlink", full)
            if stat.S_ISDIR(info.st_mode):
                fd, kind, err = _open_child(current, part)
                if fd is None:
                    if kind == "missing":
                        return opened, "missing"
                    _bail(opened, kind, full, err)
                opened.append(fd)
                return opened, "dir"
            if stat.S_ISREG(info.st_mode):
                return opened, "file"
            _bail(opened, "not_a_file", full)
        fd, kind, err = _open_child(current, part)
        prefix = "/" + "/".join(parts[: index + 1])
        if kind == "symlink":
            _bail(opened, "symlink", prefix)
        if kind == "missing":
            _bail(opened, "missing", prefix)
        if fd is None:
            _bail(opened, kind, full, err)
        opened.append(fd)
        current = fd
    return opened, "dir"


def _same_path(exc: PathRefused, path: str) -> PathRefused:
    return PathRefused(exc.kind, path, errno_name=exc.errno_name)


def real_directory(path: str) -> str:
    """Return the lexical path when every component is a real directory."""
    parts = _parts(path)
    opened: list[int] = []
    try:
        try:
            opened, kind = _walk(parts)
        except PathRefused as exc:
            raise _same_path(exc, path) from exc
        if kind == "missing":
            raise PathRefused("missing", path)
        if kind != "dir":
            raise PathRefused("not_a_directory", path)
        return "/" + "/".join(parts)
    finally:
        _close_all(opened)


def real_file(path: str) -> tuple[str, os.stat_result]:
    """Return the lexical path and lstat of a regular file. Symlinks are refused."""
    parts = _parts(path)
    opened: list[int] = []
    try:
        try:
            opened, kind = _walk(parts)
        except PathRefused as exc:
            raise _same_path(exc, path) from exc
        if kind == "missing":
            raise PathRefused("missing", path)
        if kind != "file":
            raise PathRefused("not_a_file", path)
        parent = opened[-1]
        info = os.lstat(parts[-1], dir_fd=parent)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise PathRefused("symlink" if stat.S_ISLNK(info.st_mode) else "not_a_file", path)
        if info.st_nlink < 1:
            raise PathRefused("not_a_file", path)
        return "/" + "/".join(parts), info
    finally:
        _close_all(opened)


def file_sha256(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    parts = _parts(path)
    opened: list[int] = []
    file_fd = -1
    try:
        try:
            opened, kind = _walk(parts)
        except PathRefused as exc:
            raise _same_path(exc, path) from exc
        if kind != "file":
            raise PathRefused("not_a_file", path)
        try:
            file_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=opened[-1])
        except OSError as exc:
            raise PathRefused(
                _errno_kind(exc.errno, writing=False), path, errno_name=_errname(exc.errno)
            ) from exc
        while True:
            try:
                block = os.read(file_fd, 1024 * 1024)
            except OSError as exc:
                raise PathRefused(
                    _errno_kind(exc.errno, writing=False), path, errno_name=_errname(exc.errno)
                ) from exc
            if not block:
                break
            digest.update(block)
        return digest.hexdigest()
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        _close_all(opened)


def assert_readable(path: str) -> None:
    """Open a regular file without following a symlink. Permission errors stay permission errors."""
    parts = _parts(path)
    opened: list[int] = []
    file_fd = -1
    try:
        try:
            opened, kind = _walk(parts)
        except PathRefused as exc:
            raise _same_path(exc, path) from exc
        if kind == "missing":
            raise PathRefused("missing", path)
        if kind != "file":
            raise PathRefused("not_a_file", path)
        try:
            file_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=opened[-1])
        except OSError as exc:
            raise PathRefused(
                _errno_kind(exc.errno, writing=False), path, errno_name=_errname(exc.errno)
            ) from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        _close_all(opened)


def output_name_parts(name: str, allowed: frozenset[str]) -> tuple[str, str]:
    """One path segment whose extension is in ``allowed``."""
    if not isinstance(name, str) or not name or len(name) > 120:
        raise PathRefused("bad_name", "output_name")
    if any(ord(ch) < 32 or ch in "`'/\\" for ch in name):
        raise PathRefused("bad_name", name)
    if name in (".", "..") or name.startswith("."):
        raise PathRefused("bad_name", name)
    suffix = Path(name).suffix.lower()
    if suffix not in allowed:
        raise PathRefused("bad_format", suffix or name)
    return name, suffix[1:]


def suggest_name(directory: str, name: str) -> str | None:
    """A free sibling name, or None when the first 20 candidates exist."""
    stem = Path(name).stem
    suffix = Path(name).suffix
    for index in range(2, 22):
        candidate = f"{stem}-{index}{suffix}"
        if len(candidate) > 120:
            return None
        try:
            output_state(directory, candidate)
        except PathRefused as exc:
            if exc.kind == "missing":
                return candidate
            return None
    return None


def output_state(directory: str, name: str) -> str:
    """Return file, symlink, or dir. A missing tail raises PathRefused('missing')."""
    directory = real_directory(directory)
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise PathRefused("bad_name", name or ".")
    full = directory.rstrip("/") + "/" + name
    parts = _parts(full)
    opened: list[int] = []
    try:
        opened, kind = _walk(parts)
        if kind == "missing":
            raise PathRefused("missing", full)
        if kind == "file":
            info = os.lstat(parts[-1], dir_fd=opened[-1])
            if stat.S_ISLNK(info.st_mode):
                return "symlink"
            return "file"
        return "dir"
    finally:
        _close_all(opened)


def create_exclusive(directory: str, name: str) -> str:
    """Create an empty regular file. Refuse when the name exists or is a symlink."""
    directory = real_directory(directory)
    full = directory.rstrip("/") + "/" + name
    parts = _parts(full)
    opened: list[int] = []
    file_fd = -1
    try:
        try:
            opened, kind = _walk(parts[:-1])
        except PathRefused as exc:
            raise _same_path(exc, full) from exc
        if kind != "dir":
            raise PathRefused("not_a_directory", directory)
        try:
            file_fd = os.open(parts[-1], _CREATE_FLAGS, 0o644, dir_fd=opened[-1])
        except FileExistsError as exc:
            raise PathRefused("exists", full) from exc
        except OSError as exc:
            raise PathRefused(
                _errno_kind(exc.errno, writing=True), full, errno_name=_errname(exc.errno)
            ) from exc
        return full
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        _close_all(opened)


def unlink_if_ours(path: str) -> None:
    """Remove a regular file. A symlink is left in place."""
    try:
        parts = _parts(path)
    except PathRefused:
        return
    opened: list[int] = []
    try:
        opened, kind = _walk(parts)
        if kind != "file":
            return
        info = os.lstat(parts[-1], dir_fd=opened[-1])
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            return
        os.unlink(parts[-1], dir_fd=opened[-1])
    except OSError:
        return
    finally:
        _close_all(opened)
