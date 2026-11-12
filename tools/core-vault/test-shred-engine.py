#!/usr/bin/env python3
"""Isolated destructive tests of Vault's engine, using synthetic files only."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--work-root", type=Path,
                        help="A new directory for synthetic files; must not exist.")
    parser.add_argument("--report", type=Path,
                        help="A new JSON result file; must not exist.")
    args = parser.parse_args()
    engine_path = (args.engine or Path(__file__).resolve().parents[2] /
                   "config/includes.chroot/usr/lib/core-vault-shred/engine.py").resolve()
    spec = importlib.util.spec_from_file_location("vault_shred_test_engine", engine_path)
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    spec.loader.exec_module(engine)
    if args.work_root:
        work = args.work_root.resolve()
        work.mkdir(mode=0o700, parents=False, exist_ok=False)
    else:
        work = Path(tempfile.mkdtemp(prefix="vault-shred-synthetic-tests-"))
    cases = []

    def case(name, function):
        directory = work / name
        directory.mkdir(mode=0o700)
        try:
            details = function(directory) or {}
            cases.append({"name": name, "status": "PASS", **details})
        except Exception as exc:
            cases.append({"name": name, "status": "FAIL", "error": repr(exc)})

    def rejected(paths):
        try:
            with engine.build_plan(paths):
                pass
        except (engine.PlanError, OSError):
            return
        raise AssertionError("Unsafe selection was accepted")

    def no_staging(directory):
        assert not list(directory.rglob(".vault-delete-*")), "Unexpected staging leftovers"

    def actual_fd_overwrite(d):
        target = d / "regular.bin"
        original = b"SYNTHETIC VAULT TEST DATA\n" * 2048
        target.write_bytes(original)
        read_fd = os.open(target, os.O_RDONLY | os.O_CLOEXEC)
        events = []
        try:
            with engine.build_plan([str(target)]) as plan:
                assert plan.files_count == 1 and plan.total_bytes == len(original)
                result = engine.erase(plan, threading.Event(), events.append)
                assert result.status == "completed", result.message
                assert result.completed_files == 1 and not result.leftover_paths
            overwritten = os.pread(read_fd, len(original), 0)
            assert len(overwritten) == len(original) and overwritten != original
            assert os.fstat(read_fd).st_nlink == 0 and not target.exists()
            assert any(e["phase"] == "overwriting" for e in events)
            assert all(isinstance(e["completed_files"], int) for e in events)
            no_staging(d)
            return {"bytes": len(original), "original_sha256": hashlib.sha256(original).hexdigest(),
                    "overwritten_fd_sha256": hashlib.sha256(overwritten).hexdigest(),
                    "real_gnu_shred": True}
        finally:
            os.close(read_fd)

    case("real_gnu_shred_pinned_fd", actual_fd_overwrite)

    def quick_unlink(d):
        target = d / 'readonly'
        target.write_bytes(b'synthetic quick removal')
        with target.open('rb') as reader:
            target.chmod(0)
            with engine.build_plan([target], check_overwrite=False) as plan, \
                    patch.object(engine, '_writable_anchor', side_effect=AssertionError('write-open')), \
                    patch.object(engine, '_run_shred', side_effect=AssertionError('overwrite')):
                result = engine.erase(plan, mode='quick')
            assert result.status == 'completed', result.message
            assert not target.exists() and reader.read() == b'synthetic quick removal'
        no_staging(d)
    case("quick_unlinks_without_writing_content", quick_unlink)

    def checked_before_mutation(d):
        first = d / 'a-safe'
        first.write_text('preserved')
        last = d / 'z-busy'
        last.write_text('busy')
        with engine.build_plan([first, last], check_overwrite=False) as plan, last.open('ab') as writer:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(engine, '_rename_noreplace') as rename:
                result = engine.erase(plan, mode='secure')
            assert result.status == 'error', result.message
            rename.assert_not_called()
        assert first.read_text() == 'preserved' and last.read_text() == 'busy'
        no_staging(d)
    case("secure_refuses_locked_writer_before_staging", checked_before_mutation)

    def choose_mode_after_inspection(d):
        first = d / 'a'; first.write_text('first')
        last = d / 'z'; last.write_text('second'); last.chmod(0o400)
        with engine.build_plan([first,last], check_overwrite=False) as plan, \
                patch.object(engine, '_rename_noreplace') as rename:
            result = engine.erase(plan, mode='secure')
            assert result.status == 'error' and 'read-only' in result.message
            rename.assert_not_called()
        assert first.read_text() == 'first' and last.read_text() == 'second'
        hard = d / 'linked'; os.link(first, hard)
        group = d / 'group'; group.mkdir()
        sibling = group / 'also-selected'; os.link(first, sibling)
        with engine.build_plan([first, group], check_overwrite=False) as plan:
            result = engine.erase(plan, mode='quick')
            assert result.status == 'completed' and not result.leftover_paths, result.message
        assert not first.exists() and not group.exists()
        assert hard.read_text() == 'first' and hard.stat().st_nlink == 1
        no_staging(d)
    case("secure_fails_closed_and_quick_preserves_unselected_hardlinks", choose_mode_after_inspection)

    def cancelled_inspection(d):
        target = d/'data'; target.write_text('fixture')
        event = threading.Event(); event.set()
        try:
            engine.build_plan([target], check_overwrite=False, cancel_event=event)
        except engine._Cancelled:
            pass
        else:
            raise AssertionError('Cancelled inspection was allowed')
        assert target.read_text() == 'fixture'
    case("cancellable_structural_inspection", cancelled_inspection)

    def recursive_and_dedup(d):
        root = d / "selected"
        (root / "nested").mkdir(parents=True)
        (root / "a").write_bytes(b"first")
        (root / "nested" / "b").write_bytes(b"second")
        (root / "empty").write_bytes(b"")
        outside = d / "outside.bin"
        outside.write_bytes(b"OUTSIDE SENTINEL")
        (root / "outside-link").symlink_to(outside)
        with engine.build_plan([str(root / "a"), str(root), str(root)]) as plan:
            assert plan.files_count == 3 and plan.dirs_count == 2 and plan.links_count == 1
            assert plan.total_bytes == 11 and plan.display_paths == [str(root)]
            result = engine.erase(plan, threading.Event(), None)
            assert result.status == "completed", result.message
            assert (result.completed_files, result.completed_links, result.completed_dirs) == (3, 1, 2)
        assert not root.exists() and outside.read_bytes() == b"OUTSIDE SENTINEL"
        no_staging(d)
    case("recursive_empty_symlink_and_duplicate_selection", recursive_and_dedup)

    def link_only(d):
        outside = d / "outside"
        outside.write_bytes(b"untouched")
        link = d / "selected-link"
        link.symlink_to(outside)
        with engine.build_plan([str(link)]) as plan:
            assert plan.files_count == 0 and plan.links_count == 1 and plan.total_bytes == 0
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "completed" and result.completed_links == 1
        assert not os.path.lexists(link) and outside.read_bytes() == b"untouched"
        no_staging(d)
    case("selected_symlink_removes_only_link", link_only)

    def ancestor_symlink(d):
        outside = d / "outside"
        outside.mkdir()
        target = outside / "data"
        target.write_bytes(b"never follow")
        alias = d / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        rejected([str(alias / "data")])
        assert target.read_bytes() == b"never follow"
        no_staging(d)
    case("arbitrary_symlink_ancestor_rejected", ancestor_symlink)

    def hardlink_all_preflight(d):
        safe = d / "a-safe"
        safe.write_bytes(b"safe first selection")
        linked = d / "z-linked"
        linked.write_bytes(b"hardlink original")
        alias = d / "alias"
        os.link(linked, alias)
        rejected([str(safe), str(linked)])
        assert safe.read_bytes() == b"safe first selection"
        assert linked.read_bytes() == alias.read_bytes() == b"hardlink original"
        no_staging(d)
    case("hardlinks_reject_all_before_first_write", hardlink_all_preflight)

    def fifo_all_preflight(d):
        safe = d / "a-safe"
        safe.write_bytes(b"not modified")
        fifo = d / "z-fifo"
        os.mkfifo(fifo, 0o600)
        rejected([str(safe), str(fifo)])
        assert safe.read_bytes() == b"not modified" and fifo.exists()
        no_staging(d)
    case("fifo_rejected_without_activation_or_partial_delete", fifo_all_preflight)

    def readonly_all_preflight(d):
        safe = d / "a-safe"
        safe.write_bytes(b"not modified")
        ro = d / "z-readonly"
        ro.write_bytes(b"read only")
        ro.chmod(0o400)
        rejected([str(safe), str(ro)])
        assert safe.read_bytes() == b"not modified" and ro.read_bytes() == b"read only"
        assert ro.stat().st_mode & 0o777 == 0o400
        no_staging(d)
    case("readonly_rejected_without_force", readonly_all_preflight)

    def literal_names(d):
        names = ["-", "--help", "a file", "a'quote", 'a"quote', "line\nname",
                 "$(touch INJECTION)", "semi;colon", "euro-€-č"]
        paths = []
        for name in names:
            p = d / name
            p.write_bytes(b"literal filename")
            paths.append(str(p))
        with engine.build_plan(paths) as plan:
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "completed" and result.completed_files == len(names)
        assert not list(d.iterdir()), "Unexpected shell effects or staging files"
    case("filenames_are_literal_argv_not_shell_code", literal_names)

    def file_swap(d):
        target = d / "selected"
        target.write_bytes(b"original selected inode")
        moved = d / "moved-original"
        with engine.build_plan([str(target)]) as plan:
            target.rename(moved)
            target.write_bytes(b"replacement must remain")
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "error" and result.completed_files == 0
        assert moved.read_bytes() == b"original selected inode"
        assert target.read_bytes() == b"replacement must remain"
        assert str(moved) in result.leftover_paths
        no_staging(d)
    case("top_file_inode_replacement_after_confirmation", file_swap)

    def folder_swap(d):
        target = d / "selected"
        target.mkdir()
        (target / "original").write_bytes(b"original folder")
        moved = d / "moved-original"
        with engine.build_plan([str(target)]) as plan:
            target.rename(moved)
            target.mkdir()
            (target / "replacement").write_bytes(b"new folder")
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "error" and result.completed_files == 0
        assert (moved / "original").read_bytes() == b"original folder"
        assert (target / "replacement").read_bytes() == b"new folder"
        no_staging(d)
    case("top_directory_inode_replacement_after_confirmation", folder_swap)

    def changed_child(d):
        root = d / "selected"
        root.mkdir()
        safe = root / "a-safe"
        changed = root / "z-changed"
        safe.write_bytes(b"unchanged")
        changed.write_bytes(b"first contents")
        with engine.build_plan([str(root)]) as plan:
            changed.write_bytes(b"changed contents after confirmation")
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "error" and result.completed_files == 0
        assert safe.read_bytes() == b"unchanged"
        assert changed.read_bytes() == b"changed contents after confirmation"
        no_staging(d)
    case("changed_child_detected_before_any_overwrite", changed_child)

    def changed_topology(d):
        root = d / "selected"
        root.mkdir()
        (root / "a").write_bytes(b"unchanged")
        with engine.build_plan([str(root)]) as plan:
            (root / "new").write_bytes(b"new contents")
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "error" and result.completed_files == 0
        assert (root / "a").read_bytes() == b"unchanged"
        assert (root / "new").read_bytes() == b"new contents"
        no_staging(d)
    case("folder_topology_change_before_execution", changed_topology)

    def simulated_boundary(d, top):
        root = d / "selected"
        (root / "nested").mkdir(parents=True)
        target = root / "nested" / "data"
        target.write_bytes(b"mount sentinel")
        real = engine._mount_id
        def fake(fd):
            path = os.readlink(f"/proc/self/fd/{fd}")
            boundary = str(root) if top else str(root / "nested")
            return real(fd) + (1 if path == boundary or path.startswith(boundary + "/") else 0)
        with patch.object(engine, "_mount_id", fake):
            rejected([str(root)])
        assert target.read_bytes() == b"mount sentinel"
        no_staging(d)
        return {"scope": "synthetic mount-ID gate, not an actual host mount"}
    case("selected_mount_root_guard", lambda d: simulated_boundary(d, True))
    case("nested_mount_id_guard_even_same_device", lambda d: simulated_boundary(d, False))

    def cancel_before_start(d):
        target = d / "selected"
        target.write_bytes(b"untouched")
        event = threading.Event()
        event.set()
        with engine.build_plan([str(target)]) as plan:
            result = engine.erase(plan, event, None)
        assert result.status == "cancelled" and result.completed_files == 0
        assert target.read_bytes() == b"untouched" and str(target) in result.leftover_paths
        no_staging(d)
    case("cancel_before_start_has_no_effect", cancel_before_start)

    def partial_failure(d, cancel):
        root = d / "selected"
        root.mkdir()
        first = root / "a"
        next_file = root / "b"
        first.write_bytes(b"ORIGINAL-FIRST")
        next_file.write_bytes(b"ORIGINAL-NEXT")
        event = threading.Event()
        def fail(fd, _event):
            os.write(fd, b"PART")
            if cancel:
                event.set()
                raise engine._Cancelled()
            raise OSError("Synthetic partial write failure")
        with engine.build_plan([str(root)]) as plan, patch.object(engine, "_run_shred", fail):
            result = engine.erase(plan, event, None)
        assert result.status == ("cancelled" if cancel else "error")
        assert result.completed_files == 0 and first.read_bytes() == b"PARTINAL-FIRST"
        assert next_file.read_bytes() == b"ORIGINAL-NEXT"
        assert str(root) in result.leftover_paths and "not" in result.message
        no_staging(d)
        return {"result": dataclasses.asdict(result), "synthetic_partial_writer": True}
    case("partial_failure_restores_active_and_unprocessed_entries", lambda d: partial_failure(d, False))
    case("partial_cancel_restores_active_and_unprocessed_entries", lambda d: partial_failure(d, True))

    def completed_then_failure(d):
        root = d / "selected"
        root.mkdir()
        first = root / "a"
        second = root / "b"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        real = engine._run_shred
        calls = [0]
        def fail_second(fd, event):
            calls[0] += 1
            if calls[0] == 2:
                os.write(fd, b"PART")
                raise OSError("Synthetic second file failure")
            real(fd, event)
        with engine.build_plan([str(root)]) as plan, patch.object(engine, "_run_shred", fail_second):
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "error" and result.completed_files == 1
        assert not first.exists() and second.read_bytes() == b"PARTnd"
        assert str(root) in result.leftover_paths
        no_staging(d)
    case("partial_result_does_not_restore_already_deleted_file", completed_then_failure)

    def restore_collision(d):
        target = d / "selected"
        target.write_bytes(b"ORIGINAL")
        real_rename = engine._rename_noreplace
        def inject_replacement(srcfd, src, dstfd, dst):
            real_rename(srcfd, src, dstfd, dst)
            if dst == "entry":
                target.write_bytes(b"NEW REPLACEMENT")
        def fail(fd, event):
            os.write(fd, b"PART")
            raise OSError("Synthetic failure with occupied original name")
        with engine.build_plan([str(target)]) as plan, \
                patch.object(engine, "_rename_noreplace", inject_replacement), \
                patch.object(engine, "_run_shred", fail):
            result = engine.erase(plan, threading.Event(), None)
        assert result.status == "error" and target.read_bytes() == b"NEW REPLACEMENT"
        assert len(result.leftover_paths) == 1
        preserved = Path(result.leftover_paths[0])
        assert preserved.name == "entry" and preserved.read_bytes() == b"PARTINAL"
        assert preserved.parent.name.startswith(".vault-delete-")
        assert preserved.parent.stat().st_mode & 0o777 == 0o700
        return {"result": dataclasses.asdict(result), "preserved_staging_expected": True}
    case("restore_never_overwrites_new_original_name_replacement", restore_collision)

    def active_process_cancel(d):
        target = d / "selected"
        target.write_bytes(b"ORIGINAL" * 1024)
        event = threading.Event()
        processes = []
        real_popen = subprocess.Popen
        child_code = "import os,time\nwhile True:\n os.write(1,b'P'*64)\n time.sleep(0.01)\n"
        def writer_popen(argv, **kwargs):
            assert argv == ["/usr/bin/shred", "--iterations=3", "--exact", "--verbose", "--", "-"]
            process = real_popen([sys.executable, "-c", child_code], **kwargs)
            processes.append(process)
            return process
        timer = threading.Timer(0.3, event.set)
        timer.start()
        try:
            with engine.build_plan([str(target)]) as plan, patch.object(engine.subprocess, "Popen", writer_popen):
                result = engine.erase(plan, event, None)
            assert result.status == "cancelled" and result.completed_files == 0
            assert processes and all(p.poll() is not None for p in processes)
            assert target.exists() and str(target) in result.leftover_paths
            no_staging(d)
            return {"synthetic_slow_child": True, "owned_child_stopped": True}
        finally:
            timer.cancel()
            timer.join()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
    case("active_writer_cancel_waits_for_only_owned_child", active_process_cancel)

    def staging_permissions(d, mode):
        target = d / "selected"
        target.write_bytes(b"SYNTHETIC PERMISSION SENTINEL")
        real_mkdir = engine.os.mkdir
        real_rename = engine._rename_noreplace
        stage_renames = []
        def masked_mkdir(name, mode=0o777, *, dir_fd=None):
            real_mkdir(name, mode=mode, dir_fd=dir_fd)
            if os.fspath(name).startswith(".vault-delete-"):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=dir_fd)
                try:
                    os.fchmod(fd, requested_mode)
                finally:
                    os.close(fd)
        def tracking_rename(srcfd, src, dstfd, dst):
            if dst == "entry":
                stage_renames.append(src)
            real_rename(srcfd, src, dstfd, dst)
        requested_mode = mode
        with engine.build_plan([str(target)]) as plan, \
                patch.object(engine.os, "mkdir", masked_mkdir), \
                patch.object(engine, "_rename_noreplace", tracking_rename):
            result = engine.erase(plan, threading.Event(), None)
        if mode == 0o755:
            assert result.status == "completed" and result.completed_files == 1
            assert not target.exists() and len(stage_renames) == 1
        else:
            assert result.status == "error" and result.completed_files == 0
            assert target.read_bytes() == b"SYNTHETIC PERMISSION SENTINEL"
            assert not stage_renames, "Unsafe staging must fail before selected entry rename"
            assert str(target) in result.leftover_paths
        no_staging(d)
        return {"scope": "synthetic directory-mode mask; no FAT/exFAT device mounted",
                "staging_mode": oct(mode), "renamed_selected_entry": bool(stage_renames)}
    case("staging_0755_owner_only_mutation_supported", lambda d: staging_permissions(d, 0o755))
    case("staging_0775_group_write_rejected_before_rename", lambda d: staging_permissions(d, 0o775))
    case("staging_0777_other_write_rejected_before_rename", lambda d: staging_permissions(d, 0o777))

    def plan_lifecycle(d):
        target = d / "selected"
        target.write_bytes(b"unchanged")
        plan = engine.build_plan([str(target)])
        plan.close()
        plan.close()
        result = engine.erase(plan, threading.Event(), None)
        assert result.status == "error" and target.read_bytes() == b"unchanged"
        rejected(["/"])
        rejected([str(d / ".." / "selected")])
        no_staging(d)
    case("closed_plan_and_root_parent_component_guards", plan_lifecycle)

    report = {"status": "PASS" if all(c["status"] == "PASS" for c in cases) else "FAIL",
              "engine": str(engine_path),
              "engine_sha256": hashlib.sha256(engine_path.read_bytes()).hexdigest(),
              "test_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "synthetic_work_root": str(work), "tests_count": len(cases),
              "scope": "Synthetic files only; actual GNU FD overwrite plus deterministic race/failure/cancel gates. No media-erasure or forensic recovery guarantee.",
              "tests": cases}
    if args.report:
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
        args.report.chmod(0o444)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
