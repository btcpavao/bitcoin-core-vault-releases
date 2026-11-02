"""Vault's non-privileged, confirmed file-overwrite engine.

Only ``erase`` mutates selected entries.  ``build_plan`` performs a full
no-follow preflight and keeps top-level inode and parent descriptors pinned.
The GUI owns confirmation, account/storage policy, and display of limitations.
"""
from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import secrets
import selectors
import stat
import subprocess
from dataclasses import dataclass, field
from typing import Callable


class PlanError(ValueError):
    """Selection cannot be processed safely without changing anything."""


class _Cancelled(Exception):
    pass


_LIBC = ctypes.CDLL(None, use_errno=True)
_RENAME = getattr(_LIBC, "renameat2", None)
if _RENAME is not None:
    _RENAME.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                       ctypes.c_char_p, ctypes.c_uint]
    _RENAME.restype = ctypes.c_int
_PATH_FLAGS = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_MAX_NODES = 100_000
_MAX_DEPTH = 128


def _rename_noreplace(srcfd: int, src: str, dstfd: int, dst: str) -> None:
    if _RENAME is None:
        raise PlanError("This system does not support safe no-replace renaming.")
    if _RENAME(srcfd, os.fsencode(src), dstfd, os.fsencode(dst), 1) != 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e), src)


def _mount_id(fd: int) -> int:
    with open(f"/proc/self/fdinfo/{fd}", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("mnt_id:"):
                return int(line.split(":", 1)[1])
    raise PlanError("Cannot verify the selected filesystem mount.")


def _signature(s: os.stat_result, *, ignore_ctime: bool = False) -> tuple:
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_nlink,
            s.st_size, s.st_mtime_ns, None if ignore_ctime else s.st_ctime_ns)


def _same_inode(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino, stat.S_IFMT(a.st_mode)) == (
        b.st_dev, b.st_ino, stat.S_IFMT(b.st_mode))


def _open_parent(path: str) -> tuple[int, str]:
    components = path.split("/")[1:]
    parent = os.open("/", _DIR_FLAGS)
    try:
        for component in components[:-1]:
            child = os.open(component, _DIR_FLAGS, dir_fd=parent)
            os.close(parent)
            parent = child
        return parent, components[-1]
    except BaseException:
        os.close(parent)
        raise


def _writable_anchor(anchor: int, expected: os.stat_result) -> int:
    # O_PATH avoids activating devices/FIFOs before their type is known.
    if not stat.S_ISREG(expected.st_mode):
        raise PlanError("Only regular file contents can be overwritten.")
    if expected.st_nlink != 1:
        raise PlanError("Files with multiple hard links cannot be overwritten.")
    if not expected.st_mode & 0o222:
        raise PlanError("A selected file is read-only; permissions will not be changed.")
    fd = os.open(f"/proc/self/fd/{anchor}", os.O_WRONLY | os.O_CLOEXEC)
    try:
        current = os.fstat(fd)
        if not _same_inode(expected, current) or current.st_nlink != 1:
            raise PlanError("A selected file changed while it was being opened.")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


@dataclass(frozen=True)
class _Node:
    rel: tuple[str, ...]
    kind: str
    info: os.stat_result
    mount: int


@dataclass
class _Root:
    path: str
    parent: int
    name: str
    anchor: int
    nodes: dict[tuple[str, ...], _Node] = field(default_factory=dict)


@dataclass
class Plan:
    display_paths: list[str]
    files_count: int
    dirs_count: int
    links_count: int
    total_bytes: int
    _roots: list[_Root] = field(repr=False)
    _closed: bool = field(default=False, repr=False)
    _used: bool = field(default=False, repr=False)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            for root in self._roots:
                os.close(root.anchor)
                os.close(root.parent)

    def __enter__(self) -> Plan:
        if self._closed:
            raise PlanError("The delete plan is already closed.")
        return self

    def __exit__(self, *_args) -> None:
        self.close()


@dataclass
class Result:
    status: str
    completed_files: int = 0
    completed_links: int = 0
    message: str = ""
    leftover_paths: list[str] = field(default_factory=list)
    completed_dirs: int = 0


def _record(root: _Root, parent: int, name: str, rel: tuple[str, ...],
            expected_mount: int, count: list[int]) -> None:
    if len(rel) > _MAX_DEPTH or count[0] >= _MAX_NODES:
        raise PlanError("The selected folder tree is too large or too deeply nested.")
    anchor = os.open(name, _PATH_FLAGS, dir_fd=parent)
    try:
        info = os.fstat(anchor)
        mount = _mount_id(anchor)
        if mount != expected_mount:
            raise PlanError("A selected folder contains another mounted filesystem.")
        if stat.S_ISREG(info.st_mode):
            kind = "file"
            writable = _writable_anchor(anchor, info)
            os.close(writable)
        elif stat.S_ISDIR(info.st_mode):
            kind = "dir"
        elif stat.S_ISLNK(info.st_mode):
            kind = "link"
            if info.st_nlink != 1:
                raise PlanError("Symbolic links with multiple hard links are not supported.")
        else:
            raise PlanError("Devices, sockets and named pipes cannot be deleted by this tool.")
        root.nodes[rel] = _Node(rel, kind, info, mount)
        count[0] += 1
        if kind == "dir":
            directory = os.open(name, _DIR_FLAGS, dir_fd=parent)
            try:
                if not _same_inode(info, os.fstat(directory)):
                    raise PlanError("A selected directory changed during preflight.")
                for child in sorted(os.listdir(directory)):
                    _record(root, directory, child, rel + (child,), expected_mount, count)
                if _signature(info) != _signature(os.fstat(directory)):
                    raise PlanError("A selected directory changed during preflight.")
            finally:
                os.close(directory)
        # Catch content or metadata changes during permission checks/traversal.
        if _signature(info) != _signature(os.fstat(anchor)):
            raise PlanError("A selected entry changed during preflight.")
    finally:
        os.close(anchor)


def build_plan(paths) -> Plan:
    """Inspect all selected local paths without writing, renaming or deleting."""
    if _RENAME is None:
        raise PlanError("This system does not support safe no-replace renaming.")
    normalized = set()
    for value in paths:
        path = os.fspath(value)
        if not isinstance(path, str) or "\0" in path or not path.startswith("/"):
            raise PlanError("Please select local files using absolute paths.")
        if ".." in path.split("/"):
            raise PlanError("Parent-directory components are not permitted.")
        path = os.path.normpath(path)
        if path == "/":
            raise PlanError("The filesystem root cannot be deleted.")
        normalized.add(path)
    if not normalized:
        raise PlanError("No files or folders were selected.")
    roots: list[_Root] = []
    try:
        count = [0]
        for path in sorted(normalized, key=lambda p: (len(p.split("/")), p)):
            if any(root.nodes[()].kind == "dir" and path.startswith(root.path + "/")
                   for root in roots):
                continue
            parent, name = _open_parent(path)
            anchor = -1
            try:
                if not os.access(".", os.W_OK | os.X_OK, dir_fd=parent,
                                 effective_ids=True):
                    raise PlanError("A selected entry's parent directory is not writable.")
                anchor = os.open(name, _PATH_FLAGS, dir_fd=parent)
                info = os.fstat(anchor)
                mount = _mount_id(anchor)
                if stat.S_ISDIR(info.st_mode) and mount != _mount_id(parent):
                    raise PlanError("A filesystem mount root cannot be deleted.")
                root = _Root(path, parent, name, anchor)
                _record(root, parent, name, (), mount, count)
                if _signature(info) != _signature(root.nodes[()].info):
                    raise PlanError("A selected entry changed during preflight.")
                roots.append(root)
            except BaseException:
                if anchor >= 0:
                    os.close(anchor)
                os.close(parent)
                raise
        all_nodes = [node for root in roots for node in root.nodes.values()]
        return Plan([r.path for r in roots],
                    sum(n.kind == "file" for n in all_nodes),
                    sum(n.kind == "dir" for n in all_nodes),
                    sum(n.kind == "link" for n in all_nodes),
                    sum(n.info.st_size for n in all_nodes if n.kind == "file"), roots)
    except BaseException:
        for root in roots:
            os.close(root.anchor)
            os.close(root.parent)
        raise


@dataclass
class _Stage:
    root: _Root
    name: str
    fd: int
    moved: bool = False


def _check_node(node: _Node, current: os.stat_result, *, exact: bool = True) -> None:
    # Rename legitimately updates only the selected top-level entry's ctime.
    if exact:
        same = _signature(node.info, ignore_ctime=not node.rel) == _signature(
            current, ignore_ctime=not node.rel)
    else:
        same = _same_inode(node.info, current)
    if not same:
        raise PlanError("The selected entry changed after confirmation.")


def _validate_tree(stage: _Stage) -> None:
    root = stage.root
    children: dict[tuple[str, ...], set[str]] = {}
    for rel in root.nodes:
        if rel:
            children.setdefault(rel[:-1], set()).add(rel[-1])
    def walk(parent: int, name: str, rel: tuple[str, ...]) -> None:
        node = root.nodes[rel]
        anchor = os.open(name, _PATH_FLAGS, dir_fd=parent)
        try:
            _check_node(node, os.fstat(anchor))
            if _mount_id(anchor) != node.mount:
                raise PlanError("The selected entry's filesystem mount changed.")
            if node.kind == "dir":
                directory = os.open(name, _DIR_FLAGS, dir_fd=parent)
                try:
                    _check_node(node, os.fstat(directory))
                    expected = children.get(rel, set())
                    if set(os.listdir(directory)) != expected:
                        raise PlanError("The selected folder's contents changed after confirmation.")
                    for child in sorted(expected):
                        walk(directory, child, rel + (child,))
                finally:
                    os.close(directory)
        finally:
            os.close(anchor)
    walk(stage.fd, "entry", ())


def _node_parent(stage: _Stage, node: _Node) -> tuple[int, str]:
    parent = os.dup(stage.fd)
    try:
        if not node.rel:
            return parent, "entry"
        for prefix in range(len(node.rel)):
            rel = node.rel[:prefix]
            name = "entry" if prefix == 0 else node.rel[prefix - 1]
            directory = os.open(name, _DIR_FLAGS, dir_fd=parent)
            try:
                expected = stage.root.nodes[rel]
                _check_node(expected, os.fstat(directory), exact=False)
                if _mount_id(directory) != expected.mount:
                    raise PlanError("The selected folder's filesystem mount changed.")
            except BaseException:
                os.close(directory)
                raise
            os.close(parent)
            parent = directory
        return parent, node.rel[-1]
    except BaseException:
        os.close(parent)
        raise


def _path(stage: _Stage, node: _Node | None = None) -> str:
    actual = os.readlink(f"/proc/self/fd/{stage.fd}")
    if node is None:
        return actual
    return os.path.join(actual, "entry", *node.rel)


def _notify(callback: Callable | None, phase: str, path: str, plan: Plan,
            result: Result) -> None:
    if callback:
        try:
            callback({"phase": phase, "path": path,
                      "completed_files": result.completed_files,
                      "total_files": plan.files_count,
                      "completed_links": result.completed_links,
                      "total_links": plan.links_count})
        except Exception:
            # Display failures must not interrupt an active overwrite operation.
            pass


def _check_cancel(event) -> None:
    if event is not None and event.is_set():
        raise _Cancelled()


def _run_shred(fd: int, event) -> None:
    """Write only the verified fd; no selected path is passed to GNU shred."""
    os.lseek(fd, 0, os.SEEK_SET)
    env = dict(os.environ, LC_ALL="C")
    process = subprocess.Popen(
        ["/usr/bin/shred", "--iterations=1", "--exact", "--verbose", "--", "-"],
        stdin=subprocess.DEVNULL, stdout=fd, stderr=subprocess.PIPE,
        close_fds=True, env=env)
    tail = bytearray()
    cancelled = False
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stderr, selectors.EVENT_READ)
        while process.poll() is None:
            if event is not None and event.is_set():
                cancelled = True
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                break
            for key, _mask in selector.select(0.1):
                block = os.read(key.fd, 4096)
                if block:
                    tail.extend(block)
                    if len(tail) > 8192:
                        del tail[:-8192]
                else:
                    selector.unregister(key.fd)
        remainder = process.stderr.read()
        tail.extend(remainder[-8192:])
        if cancelled:
            raise _Cancelled()
        if process.returncode != 0:
            detail = bytes(tail[-8192:]).decode("utf-8", "replace").strip()
            raise OSError("File overwrite failed" + (": " + detail if detail else "."))
        os.fsync(fd)
    finally:
        selector.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stderr.close()


def _restore(stages: list[_Stage]) -> tuple[list[str], list[str]]:
    leftovers: list[str] = []
    notes: list[str] = []
    for stage in reversed(stages):
        root = stage.root
        if stage.moved:
            try:
                os.stat("entry", dir_fd=stage.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError:
                leftovers.append(_path(stage))
                notes.append("A remaining entry could not be inspected; its staging folder was preserved.")
            else:
                try:
                    _rename_noreplace(stage.fd, "entry", root.parent, root.name)
                    leftovers.append(os.path.join(os.readlink(f"/proc/self/fd/{root.parent}"), root.name))
                except OSError:
                    leftovers.append(_path(stage, root.nodes[()]))
                    notes.append("An original pathname is occupied; its remaining data was kept in the staging folder.")
        try:
            named = os.stat(stage.name, dir_fd=root.parent, follow_symlinks=False)
            if not _same_inode(named, os.fstat(stage.fd)):
                raise OSError("The staging folder's pathname changed.")
            os.rmdir(stage.name, dir_fd=root.parent)
        except OSError:
            remaining = _path(stage)
            if not any(p == remaining or p.startswith(remaining + "/") for p in leftovers):
                leftovers.append(remaining)
                notes.append("A staging folder could not be removed; it was preserved.")
        finally:
            os.close(stage.fd)
    return list(dict.fromkeys(leftovers)), list(dict.fromkeys(notes))


def erase(plan: Plan, cancel_event=None, progress_callback=None) -> Result:
    """Execute a GUI-confirmed plan once; errors/cancel preserve remaining entries."""
    if plan._closed or plan._used:
        return Result("error", message="This delete plan is closed or has already been used.")
    plan._used = True
    result = Result("error")
    stages: list[_Stage] = []
    try:
        _check_cancel(cancel_event)
        # Recheck every root before changing *any* selected pathname.
        for root in plan._roots:
            _notify(progress_callback, "preparing", root.path, plan, result)
            current = os.stat(root.name, dir_fd=root.parent, follow_symlinks=False)
            if _signature(current) != _signature(root.nodes[()].info):
                raise PlanError("The selected entry changed after confirmation.")
            if _signature(os.fstat(root.anchor)) != _signature(current):
                raise PlanError("The selected inode no longer matches its original pathname.")
        for root in plan._roots:
            _check_cancel(cancel_event)
            stage_name = ".vault-delete-" + secrets.token_hex(12)
            os.mkdir(stage_name, mode=0o700, dir_fd=root.parent)
            try:
                stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root.parent)
            except BaseException:
                os.rmdir(stage_name, dir_fd=root.parent)
                raise
            stage = _Stage(root, stage_name, stage_fd)
            stages.append(stage)
            info = os.fstat(stage_fd)
            permissions = stat.S_IMODE(info.st_mode)
            # Request 0700, but FAT/exFAT mount masks may expose it as 0755.
            # Isolation needs owner-only mutation: other users may not rename
            # or replace entries here. Original file permissions are unchanged.
            if (info.st_uid != os.geteuid() or permissions & 0o700 != 0o700
                    or permissions & 0o022):
                raise PlanError("The filesystem cannot create an owner-controlled staging folder without group or other write access.")
            if _mount_id(stage_fd) != root.nodes[()].mount:
                raise PlanError("The staging folder is on a different filesystem mount.")
            _rename_noreplace(root.parent, root.name, stage_fd, "entry")
            stage.moved = True
        # Full staged tree validation precedes all overwrite/unlink operations.
        for stage in stages:
            _check_cancel(cancel_event)
            _validate_tree(stage)
        for kind in ("file", "link", "dir"):
            for stage in stages:
                nodes = [n for n in stage.root.nodes.values() if n.kind == kind]
                if kind == "dir":
                    nodes.sort(key=lambda n: len(n.rel), reverse=True)
                for node in nodes:
                    _check_cancel(cancel_event)
                    display = os.path.join(stage.root.path, *node.rel)
                    _notify(progress_callback, "overwriting" if kind == "file" else "removing",
                            display, plan, result)
                    parent, name = _node_parent(stage, node)
                    anchor = writable = -1
                    try:
                        anchor = os.open(name, _PATH_FLAGS, dir_fd=parent)
                        _check_node(node, os.fstat(anchor), exact=kind != "dir")
                        if _mount_id(anchor) != node.mount:
                            raise PlanError("The selected entry's filesystem mount changed.")
                        if kind == "file":
                            writable = _writable_anchor(anchor, os.fstat(anchor))
                            # Recheck after gaining the advisory lock.
                            _check_node(node, os.fstat(writable))
                            _check_cancel(cancel_event)
                            _run_shred(writable, cancel_event)
                            after = os.fstat(writable)
                            if after.st_nlink != 1 or after.st_size != node.info.st_size:
                                raise PlanError("The file changed while its contents were overwritten.")
                            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                            if not _same_inode(after, current):
                                raise PlanError("The overwritten file's pathname changed; remaining entries were preserved.")
                            os.unlink(name, dir_fd=parent)
                            result.completed_files += 1
                        elif kind == "link":
                            os.unlink(name, dir_fd=parent)
                            result.completed_links += 1
                        else:
                            os.rmdir(name, dir_fd=parent)
                            result.completed_dirs += 1
                    finally:
                        if writable >= 0:
                            os.close(writable)
                        if anchor >= 0:
                            os.close(anchor)
                        os.close(parent)
        result.status = "completed"
        result.message = "Selected file contents were overwritten and the selected entries were deleted."
    except _Cancelled:
        result.status = "cancelled"
        result.message = "Stopped. Already overwritten or deleted data cannot be restored by this action; remaining entries were kept."
    except Exception as exc:
        result.status = "error"
        result.message = "Stopped: " + str(exc) + " Already overwritten or deleted data is not restored; remaining entries were kept."
    finally:
        leftovers, notes = _restore(stages)
        # Include selections that were never staged (e.g. an early cancellation).
        # The pinned O_PATH descriptor also tracks a selected entry renamed by
        # somebody else; no arbitrary replacement is opened or deleted here.
        for root in plan._roots:
            if os.fstat(root.anchor).st_nlink:
                actual = os.readlink(f"/proc/self/fd/{root.anchor}")
                if actual not in leftovers:
                    leftovers.append(actual)
        result.leftover_paths = leftovers
        if leftovers and result.status == "completed":
            result.status = "error"
        if notes:
            result.message += " " + " ".join(notes)
    return result
