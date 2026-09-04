from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import collector


@contextmanager
def temporary_cache():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        root = base / "omarchy" / collector.PLUGIN_ID
        with (
            mock.patch.object(collector, "CACHE_BASE", base),
            mock.patch.object(collector, "CACHE_ROOT", root),
            mock.patch.object(collector, "CACHE_FILE", root / "status.json"),
            mock.patch.object(collector, "LOCK_FILE", root / "refresh.lock"),
        ):
            yield base, root


class CacheSecurityTests(unittest.TestCase):
    def test_cache_permissions_and_round_trip(self) -> None:
        with temporary_cache() as (_, root):
            payload = {
                "schemaVersion": 1,
                "fetchedAtMs": 123,
                "accounts": [{"id": "one", "label": "Profile 1", "limits": [], "resets": []}],
            }
            collector.write_cache(payload)

            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root / "status.json").stat().st_mode), 0o600)
            self.assertEqual(collector.read_cache()["accounts"][0]["label"], "Profile 1")

    def test_lock_symlink_is_refused_without_touching_target(self) -> None:
        with temporary_cache() as (base, root):
            directory = collector.ensure_cache_root()
            os.close(directory)
            target = base / "target"
            target.write_text("keep", encoding="utf-8")
            os.symlink(target, root / "refresh.lock")

            directory = collector.ensure_cache_root()
            try:
                with self.assertRaises(OSError):
                    collector._open_lock(directory)
            finally:
                os.close(directory)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_existing_owned_lock_is_made_private(self) -> None:
        with temporary_cache() as (_, root):
            directory = collector.ensure_cache_root()
            (root / "refresh.lock").write_text("", encoding="utf-8")
            (root / "refresh.lock").chmod(0o644)
            lock = collector._open_lock(directory)
            try:
                self.assertEqual(stat.S_IMODE(os.fstat(lock).st_mode), 0o600)
            finally:
                os.close(lock)
                os.close(directory)

    def test_lock_wait_has_a_deadline(self) -> None:
        with temporary_cache():
            directory = collector.ensure_cache_root()
            first = collector._open_lock(directory)
            second = collector._open_lock(directory)
            try:
                collector._acquire_lock(first, time.monotonic() + 1)
                with self.assertRaises(TimeoutError):
                    collector._acquire_lock(second, time.monotonic() + 0.02)
            finally:
                os.close(first)
                os.close(second)
                os.close(directory)

    def test_status_symlink_is_not_read(self) -> None:
        with temporary_cache() as (base, root):
            directory = collector.ensure_cache_root()
            os.close(directory)
            target = base / "outside.json"
            target.write_text('{"schemaVersion":1,"accounts":[]}', encoding="utf-8")
            os.symlink(target, root / "status.json")

            self.assertEqual(collector.read_cache()["error"], "No cached result yet")


class ProfileSecurityTests(unittest.TestCase):
    def test_private_profile_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile-one"
            profile.mkdir(mode=0o700)
            auth = profile / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            auth.chmod(0o600)

            collector.validate_profile(profile)

    def test_auth_symlink_and_public_auth_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile-one"
            profile.mkdir(mode=0o700)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            outside.chmod(0o600)
            os.symlink(outside, profile / "auth.json")
            with self.assertRaises(OSError):
                collector.validate_profile(profile)

            (profile / "auth.json").unlink()
            (profile / "auth.json").write_text("{}", encoding="utf-8")
            (profile / "auth.json").chmod(0o644)
            with self.assertRaises(collector.UnsafePathError):
                collector.validate_profile(profile)

    def test_symlinked_profile_is_not_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir(mode=0o700)
            os.symlink(real, root / "linked")

            self.assertEqual(collector.discover_profiles(root), [real])


class ProcessSecurityTests(unittest.TestCase):
    def test_codex_resolution_does_not_use_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trusted = root / "codex"
            trusted.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            trusted.chmod(0o700)
            with (
                mock.patch.object(collector, "CODEX_CANDIDATES", (trusted,)),
                mock.patch.dict(os.environ, {"PATH": "/untrusted"}),
            ):
                self.assertEqual(collector.resolve_codex_command(), trusted)

    def test_runtime_environment_removes_loader_and_python_injection(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LD_PRELOAD": "bad", "LD_LIBRARY_PATH": "bad", "PYTHONHOME": "bad", "PYTHONPATH": "bad"},
        ):
            env = collector.runtime_environment(Path("/profiles/one"), Path("/trusted/bin/codex"))
        for key in ("LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH"):
            self.assertNotIn(key, env)
        self.assertEqual(env["CODEX_HOME"], "/profiles/one")
        self.assertTrue(env["PATH"].startswith("/trusted/bin:"))

    def test_rpc_reads_partial_binary_output(self) -> None:
        program = """
import json, sys, time
request = json.loads(sys.stdin.buffer.readline())
reply = json.dumps({"id": request["id"], "result": {"ok": True}}).encode() + b"\\n"
sys.stdout.buffer.write(reply[:5])
sys.stdout.buffer.flush()
time.sleep(0.02)
sys.stdout.buffer.write(reply[5:])
sys.stdout.buffer.flush()
"""
        process = subprocess.Popen(
            ["/usr/bin/python3", "-I", "-c", program],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        try:
            channel = collector.RpcChannel(process, time.monotonic() + 2)
            self.assertTrue(channel.request(7, "test")["result"]["ok"])
        finally:
            collector.terminate_process_group(process)

    def test_rpc_line_limit_is_enforced(self) -> None:
        program = f"import sys; sys.stdout.buffer.write(b'x' * {collector.MAX_RPC_LINE_BYTES + 1}); sys.stdout.buffer.flush()"
        process = subprocess.Popen(
            ["/usr/bin/python3", "-I", "-c", program],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        try:
            channel = collector.RpcChannel(process, time.monotonic() + 2)
            with self.assertRaises(ValueError):
                channel.request(1, "test")
        finally:
            collector.terminate_process_group(process)

    def test_rpc_request_has_a_deadline(self) -> None:
        process = subprocess.Popen(
            ["/usr/bin/sleep", "30"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        try:
            channel = collector.RpcChannel(process, time.monotonic() + 0.02)
            with self.assertRaises(TimeoutError):
                channel.request(1, "test")
        finally:
            collector.terminate_process_group(process)

    def test_process_group_cleanup_stops_descendants(self) -> None:
        program = """
import subprocess, sys, time
child = subprocess.Popen(["/usr/bin/sleep", "30"])
print(child.pid, flush=True)
time.sleep(30)
"""
        process = subprocess.Popen(
            ["/usr/bin/python3", "-I", "-c", program],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        assert process.stdout is not None
        child_pid = int(process.stdout.readline())

        collector.terminate_process_group(process)

        state_path = Path(f"/proc/{child_pid}/stat")
        for _ in range(20):
            if not state_path.exists() or state_path.read_text(encoding="utf-8").split()[2] == "Z":
                break
            time.sleep(0.01)
        else:
            self.fail("Codex descendant was left running")


class PayloadTests(unittest.TestCase):
    def test_payload_lists_and_text_are_bounded(self) -> None:
        account = {
            "id": "x" * 1000,
            "label": "label",
            "limits": [{"name": "5 hour", "usedPercent": 50}] * 20,
            "resets": [{"title": "reset"}] * 40,
        }
        payload = collector.sanitize_payload(
            {"schemaVersion": 1, "accounts": [account] * 100, "error": ""}
        )

        self.assertEqual(len(payload["accounts"]), collector.MAX_PROFILES)
        self.assertEqual(len(payload["accounts"][0]["limits"]), collector.MAX_LIMITS)
        self.assertEqual(len(payload["accounts"][0]["resets"]), collector.MAX_RESETS)
        self.assertEqual(len(payload["accounts"][0]["id"]), collector.MAX_TEXT_LENGTH)

    def test_identity_is_removed_from_default_output(self) -> None:
        payload = collector.redact_identity(
            {
                "schemaVersion": 1,
                "includesIdentity": True,
                "accounts": [{"id": "one", "email": "person@example.com", "plan": "Plus"}],
            }
        )

        self.assertFalse(payload["includesIdentity"])
        self.assertNotIn("email", payload["accounts"][0])
        self.assertNotIn("plan", payload["accounts"][0])

    def test_profile_path_length_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            collector.resolve_profile_root("/" + "x" * collector.MAX_PATH_LENGTH)


if __name__ == "__main__":
    unittest.main()
