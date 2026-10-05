"""Symlink-safe file access inside trees the container controls (plan 7.6, S6).

The LLM owns the notes worktree (/work), the reviewer's out/ folder and the session dir;
it may swap any file or directory for a symlink at any moment, also while host code runs.
Every access here resolves the path relative to an fd of the trusted root with openat2 and
RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS, so no component may be a symlink and nothing outside
the root is ever reached – there is no check-then-use window. Writes go to a temporary file
created with O_EXCL in the already opened parent directory and are renamed into place.
"""

import ctypes
import errno
import fnmatch
import json
import os
import shutil
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from .errors import NeedsOwner

SYS_OPENAT2 = 437                      # x86_64 and aarch64
RESOLVE_NO_MAGICLINKS = 0x02
RESOLVE_NO_SYMLINKS = 0x04
RESOLVE_BENEATH = 0x08
RESOLVE = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS
UNSAFE_ERRNOS = (errno.ELOOP, errno.EXDEV)


class UnsafePath(NeedsOwner):
    """A symlink, a non-regular file or an escape inside a container-controlled tree."""


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


_libc = ctypes.CDLL(None, use_errno=True)
_syscall = _libc.syscall
_syscall.restype = ctypes.c_long
_syscall.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
                     ctypes.c_size_t]
_HAVE_OPENAT2 = True
TMP_PREFIX = ".sn-tmp-"
STALE_TMP_S = 600         # an older temp file of ours was left by a killed process


def _parts(rel) -> list[str]:
    """Validated components of a repo-relative path ('' or '.' is the root itself)."""
    text = str(rel)
    pure = PurePosixPath(text)
    if pure.is_absolute() or "\0" in text:
        raise UnsafePath(f"{text}: not a relative path", todo="inspect the worktree")
    parts = [p for p in pure.parts if p != "."]
    if ".." in parts:
        raise UnsafePath(f"{text}: path leaves the tree", todo="inspect the worktree")
    return parts


def _unsafe(rel, exc: OSError) -> UnsafePath:
    return UnsafePath(f"{rel}: symlink or path outside the tree ({exc.strerror})",
                      todo="remove the symlink from the worktree (school-notes chat)")


def _openat2(dirfd: int, rel: str, flags: int, mode: int = 0) -> int:
    global _HAVE_OPENAT2
    if _HAVE_OPENAT2:
        how = _OpenHow(flags | os.O_CLOEXEC, mode, RESOLVE)
        fd = _syscall(SYS_OPENAT2, dirfd, rel.encode("utf-8"), ctypes.byref(how),
                      ctypes.sizeof(how))
        if fd >= 0:
            return fd
        err = ctypes.get_errno()
        if err != errno.ENOSYS:
            raise OSError(err, os.strerror(err), rel)
        _HAVE_OPENAT2 = False
    return _walk_open(dirfd, rel, flags, mode)


def _walk_open(dirfd: int, rel: str, flags: int, mode: int) -> int:
    """Fallback without openat2: open component by component with O_NOFOLLOW."""
    parts = rel.split("/") if rel else []
    current = os.dup(dirfd)
    try:
        for part in parts[:-1]:
            if part == ".." or stat.S_ISLNK(os.stat(part, dir_fd=current,
                                                    follow_symlinks=False).st_mode):
                raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), rel)
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                          dir_fd=current)
            os.close(current)
            current = nxt
        if not parts:
            return os.open(".", flags | os.O_CLOEXEC, dir_fd=current)
        return os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=current)
    finally:
        os.close(current)


@contextmanager
def _root_fd(root):
    fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _open(root, rel, flags: int, mode: int = 0):
    """An fd for `rel` below `root`; symlinks and escapes raise UnsafePath."""
    joined = "/".join(_parts(rel))
    with _root_fd(root) as rfd:
        try:
            fd = _openat2(rfd, joined or ".", flags, mode)
        except OSError as exc:
            if exc.errno in UNSAFE_ERRNOS:
                raise _unsafe(rel, exc) from None
            raise
    try:
        yield fd
    finally:
        os.close(fd)


def read_bytes(root, rel) -> bytes:
    with _open(root, rel, os.O_RDONLY | os.O_NOFOLLOW) as fd:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnsafePath(f"{rel}: not a regular file", todo="inspect the worktree")
        chunks = []
        while block := os.read(fd, 1 << 20):
            chunks.append(block)
        return b"".join(chunks)


def read_text(root, rel, encoding: str = "utf-8", errors: str = "strict") -> str:
    return read_bytes(root, rel).decode(encoding, errors)


def _kind(root, rel) -> int | None:
    """st_mode of `rel` (no symlink allowed anywhere), None when it does not exist."""
    try:
        with _open(root, rel, os.O_PATH | os.O_NOFOLLOW) as fd:
            mode = os.fstat(fd).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISLNK(mode):   # O_PATH|O_NOFOLLOW returns a trailing link itself (both paths)
        raise UnsafePath(f"{rel}: symlink", todo="remove the symlink from the worktree")
    return mode


def mode(root, rel) -> int | None:
    """st_mode of `rel` without following anything; None when it does not exist."""
    return _kind(root, rel)


def exists(root, rel) -> bool:
    return _kind(root, rel) is not None


def is_file(root, rel) -> bool:
    mode = _kind(root, rel)
    return mode is not None and stat.S_ISREG(mode)


def is_dir(root, rel) -> bool:
    mode = _kind(root, rel)
    return mode is not None and stat.S_ISDIR(mode)


def _open_dir(root, rel, create: bool) -> int:
    """An fd of directory `rel` (created component by component when `create`)."""
    parts = _parts(rel)
    with _root_fd(root) as rfd:
        current = os.dup(rfd)
    try:
        for part in parts:
            nxt = _open_component(current, part, rel, create)
            os.close(current)
            current = nxt
        return current
    except BaseException:
        os.close(current)
        raise


def _open_component(dirfd: int, part: str, rel, create: bool) -> int:
    """One directory component below `dirfd`, created when missing and `create`; a link
    (also one planted between mkdir and open) raises UnsafePath."""
    try:
        try:
            return _openat2(dirfd, part, os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(part, 0o755, dir_fd=dirfd)
            except FileExistsError:
                pass
            return _openat2(dirfd, part, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        if exc.errno in UNSAFE_ERRNOS or exc.errno == errno.ENOTDIR:
            raise _unsafe(rel, exc) from None
        raise


@contextmanager
def _parent(root, rel, create: bool):
    parts = _parts(rel)
    if not parts:
        raise UnsafePath(f"{rel}: the root itself", todo="inspect the worktree")
    fd = _open_dir(root, "/".join(parts[:-1]), create)
    try:
        yield fd, parts[-1]
    finally:
        os.close(fd)


def makedirs(root, rel) -> None:
    os.close(_open_dir(root, rel, create=True))


def write_bytes(root, rel, data: bytes, mode: int = 0o644) -> None:
    """Atomic write; a symlink at the target is replaced, never followed."""
    with _parent(root, rel, create=True) as (pfd, name):
        _sweep_stale_tmp(pfd)
        tmp = f"{TMP_PREFIX}{uuid.uuid4().hex}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=pfd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
            os.replace(tmp, name, src_dir_fd=pfd, dst_dir_fd=pfd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=pfd)
            except FileNotFoundError:
                pass
            raise


def _sweep_stale_tmp(pfd: int) -> None:
    """Remove our own temp files a killed process left (old ones only: a concurrent writer's
    fresh temp file is not touched). A planted link of that name is removed, not followed."""
    now = time.time()
    for name in os.listdir(pfd):
        if not name.startswith(TMP_PREFIX):
            continue
        try:
            info = os.stat(name, dir_fd=pfd, follow_symlinks=False)
            if now - info.st_mtime > STALE_TMP_S or stat.S_ISLNK(info.st_mode):
                os.unlink(name, dir_fd=pfd)
        except FileNotFoundError:
            pass


def write_text(root, rel, text: str, mode: int = 0o644) -> None:
    write_bytes(root, rel, text.encode("utf-8"), mode)


def copy_in(src: Path, root, rel, mode: int = 0o644) -> None:
    """Copy a trusted host file into the tree."""
    write_bytes(root, rel, Path(src).read_bytes(), mode)


def unlink(root, rel, missing_ok: bool = True) -> None:
    """Remove a file (a symlink is removed itself, never followed)."""
    try:
        with _parent(root, rel, create=False) as (pfd, name):
            os.unlink(name, dir_fd=pfd)
    except FileNotFoundError:
        if not missing_ok:
            raise


def rmtree(root, rel, missing_ok: bool = True) -> None:
    """Remove a directory tree with fd-based traversal (shutil's dir_fd variant)."""
    try:
        with _parent(root, rel, create=False) as (pfd, name):
            mode = os.stat(name, dir_fd=pfd, follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                shutil.rmtree(name, dir_fd=pfd)
            else:
                os.unlink(name, dir_fd=pfd)
    except FileNotFoundError:
        if not missing_ok:
            raise


def listdir(root, rel="") -> list[str]:
    fd = _open_dir(root, rel, create=False)
    try:
        return sorted(os.listdir(fd))
    finally:
        os.close(fd)


def walk_files(root, rel="") -> list[str]:
    """Repo-relative paths of the regular files below `rel`; symlinks and other non-regular
    entries are skipped (the path guard reports them), symlinked dirs are never entered."""
    base = "/".join(_parts(rel))
    try:
        fd = _open_dir(root, base, create=False)
    except (FileNotFoundError, NotADirectoryError, UnsafePath):
        return []            # missing, or a link: never entered (the guard reports links)
    out: list[str] = []
    _walk(fd, base, out)
    return sorted(out)


def _walk(fd: int, prefix: str, out: list[str]) -> None:
    try:
        for name in os.listdir(fd):
            rel = f"{prefix}/{name}" if prefix else name
            mode = os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
            if stat.S_ISREG(mode):
                out.append(rel)
            elif stat.S_ISDIR(mode):
                try:
                    sub = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                  | os.O_CLOEXEC, dir_fd=fd)
                except OSError:          # swapped for a link meanwhile: not entered
                    continue
                _walk(sub, rel, out)
    finally:
        os.close(fd)


def glob(root, rel: str, pattern: str) -> list[str]:
    """`walk_files` below `rel` filtered with a root-relative glob (`*` within one path
    segment, `**` for any number of segments)."""
    want = pattern.split("/")
    return [p for p in walk_files(root, rel) if _match(p.split("/"), want)]


def _match(parts: list[str], pattern: list[str]) -> bool:
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return any(_match(parts[i:], pattern[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pattern[0]) and \
        _match(parts[1:], pattern[1:])


def rel_of(root, path) -> str:
    """The repo-relative POSIX form of `path` below `root` (no resolution of links)."""
    return PurePosixPath(os.path.relpath(str(path), str(root))).as_posix()


def read_json(root, rel, default=None):
    """JSON from the tree; `default` when the file does not exist."""
    try:
        return json.loads(read_text(root, rel))
    except FileNotFoundError:
        return default


def write_json(root, rel, value, mode: int = 0o644) -> None:
    write_text(root, rel, json.dumps(value, ensure_ascii=False, indent=2) + "\n", mode)


