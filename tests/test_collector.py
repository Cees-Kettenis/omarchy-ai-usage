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
            auth = real / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            auth.chmod(0o600)
            os.symlink(real, root / "linked")

            self.assertEqual(collector.discover_profiles(root), [real])

    def test_provider_markers_keep_profiles_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex-account"
            claude = root / "claude-account"
            codex.mkdir(mode=0o700)
            claude.mkdir(mode=0o700)
            (codex / "auth.json").write_text("{}", encoding="utf-8")
            (claude / ".credentials.json").write_text("{}", encoding="utf-8")

            self.assertEqual(collector.discover_profiles(root), [codex])
            self.assertEqual(collector.discover_claude_profiles(root), [claude])

    def test_direct_claude_home_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            credentials = profile / ".credentials.json"
            credentials.write_text("{}", encoding="utf-8")
            credentials.chmod(0o600)

            self.assertEqual(collector.discover_claude_profiles(profile), [profile])

    def test_multiple_claude_config_homes_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("personal", "work"):
                profile = root / name
                profile.mkdir(mode=0o700)
                credentials = profile / ".credentials.json"
                credentials.write_text("{}", encoding="utf-8")
                credentials.chmod(0o600)

            self.assertEqual(
                collector.discover_claude_profiles(root),
                [root / "personal", root / "work"],
            )

    def test_claude_discovery_modes_do_not_cross_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root_credentials = root / ".credentials.json"
            root_credentials.write_text("{}", encoding="utf-8")
            root_credentials.chmod(0o600)
            child = root / "child"
            child.mkdir(mode=0o700)
            child_credentials = child / ".credentials.json"
            child_credentials.write_text("{}", encoding="utf-8")
            child_credentials.chmod(0o600)

            self.assertEqual(collector.discover_claude_profiles(root, "single"), [root])
            self.assertEqual(collector.discover_claude_profiles(root, "multiple"), [])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "child"
            child.mkdir(mode=0o700)
            credentials = child / ".credentials.json"
            credentials.write_text("{}", encoding="utf-8")
            credentials.chmod(0o600)

            self.assertEqual(collector.discover_claude_profiles(root, "single"), [])
            self.assertEqual(collector.discover_claude_profiles(root, "multiple"), [child])

    def test_dual_marker_directories_are_ignored_by_both_providers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ambiguous = root / "ambiguous"
            ambiguous.mkdir(mode=0o700)
            for marker in ("auth.json", ".credentials.json"):
                path = ambiguous / marker
                path.write_text("{}", encoding="utf-8")
                path.chmod(0o600)

            self.assertEqual(collector.discover_profiles(root), [])
            self.assertEqual(collector.discover_claude_profiles(root, "multiple"), [])

    def test_legacy_claude_root_migrates_to_single_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "shell.json"
            settings_file.write_text(
                json.dumps(
                    {
                        "bar": {
                            "layout": {
                                "right": [
                                    {
                                        "id": collector.PLUGIN_ID,
                                        "profilesRoot": "/codex-old",
                                        "claudeProfilesRoot": "/claude-old",
                                    }
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(collector, "SHELL_CONFIG_FILE", settings_file):
                codex, single, multiple, mode = collector.configured_provider_settings()

            self.assertEqual(codex, "/codex-old")
            self.assertEqual(single, "/claude-old")
            self.assertIsNone(multiple)
            self.assertEqual(mode, "single")

    def test_multiple_claude_mode_uses_its_separate_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "shell.json"
            settings_file.write_text(
                json.dumps(
                    {
                        "bar": {
                            "layout": {
                                "right": [
                                    {
                                        "id": collector.PLUGIN_ID,
                                        "codexProfilesRoot": "/codex",
                                        "claudeProfileMode": "Multiple accounts",
                                        "claudeProfileRoot": "/claude-single",
                                        "claudeProfilesRoot": "/claude-many",
                                    }
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(collector, "SHELL_CONFIG_FILE", settings_file):
                codex, claude, mode = collector.resolve_profile_configuration(None, None, None)

            self.assertEqual(codex, Path("/codex"))
            self.assertEqual(claude, Path("/claude-many"))
            self.assertEqual(mode, "multiple")


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

    def test_claude_environment_selects_one_profile_and_removes_overrides(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "wrong-account",
                "ANTHROPIC_BASE_URL": "https://example.invalid",
                "CLAUDE_CODE_OAUTH_TOKEN": "wrong-account",
                "CLAUDE_CONFIG_DIR": "/wrong/profile",
            },
        ):
            env = collector.claude_runtime_environment(
                Path("/profiles/claude-one"), Path("/trusted/bin/claude")
            )
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/profiles/claude-one")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)

    def test_claude_probe_uses_official_auth_status_and_local_snapshot(self) -> None:
        process = mock.Mock()
        process.pid = 12345
        profile = Path("/profiles/claude-one")
        command = Path("/trusted/bin/claude")
        with (
            mock.patch.object(collector, "validate_claude_profile"),
            mock.patch.object(collector.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(
                collector,
                "_bounded_process_output",
                return_value=json.dumps(
                    {
                        "loggedIn": True,
                        "email": "person@example.com",
                        "subscriptionType": "pro",
                    }
                ).encode(),
            ),
            mock.patch.object(
                collector,
                "read_claude_status",
                return_value={
                    "capturedAtMs": 123,
                    "limits": [{"name": "5 hour", "usedPercent": 25}],
                },
            ),
            mock.patch.object(collector, "terminate_process_group"),
        ):
            account = collector.probe_claude_profile(
                profile, command, True, time.monotonic() + 5
            )

        self.assertEqual(popen.call_args.args[0], [str(command), "auth", "status"])
        self.assertEqual(popen.call_args.kwargs["env"]["CLAUDE_CONFIG_DIR"], str(profile))
        self.assertEqual(account["provider"], "claude")
        self.assertEqual(account["email"], "person@example.com")
        self.assertEqual(account["plan"], "Pro")
        self.assertEqual(account["limits"][0]["name"], "5 hour")

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

        self.assertEqual(len(payload["accounts"]), collector.MAX_ACCOUNTS)
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

    def test_claude_statusline_uses_documented_rate_limit_fields(self) -> None:
        profile = Path("/profiles/claude-one")
        snapshot = collector.normalize_claude_statusline(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 23.5, "resets_at": 1000},
                    "seven_day": {"used_percentage": 41.2, "resets_at": 2000},
                },
                "transcript_path": "/private/conversation.jsonl",
            },
            profile,
        )

        self.assertEqual([entry["name"] for entry in snapshot["limits"]], ["5 hour", "Weekly"])
        self.assertEqual(snapshot["limits"][0]["remainingPercent"], 76)
        self.assertNotIn("transcript_path", snapshot)

    def test_claude_statusline_cache_is_private_and_profile_scoped(self) -> None:
        with temporary_cache() as (_, root):
            profile = Path("/profiles/claude-one")
            collector.capture_claude_statusline(
                {
                    "rate_limits": {
                        "five_hour": {
                            "used_percentage": 25,
                            "resets_at": int(time.time()) + 3600,
                        }
                    }
                },
                profile,
            )

            snapshot = collector.read_claude_status(profile)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot["limits"][0]["remainingPercent"], 75)
            cache_file = root / collector._claude_status_name(profile)
            self.assertEqual(stat.S_IMODE(cache_file.stat().st_mode), 0o600)

    def test_expired_claude_windows_are_not_reused(self) -> None:
        with temporary_cache():
            profile = Path("/profiles/claude-one")
            collector.capture_claude_statusline(
                {"rate_limits": {"five_hour": {"used_percentage": 99, "resets_at": 1}}},
                profile,
            )

            snapshot = collector.read_claude_status(profile)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot["limits"], [])

    def test_statusline_bridge_runs_in_isolated_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = os.environ.copy()
            environment["XDG_CACHE_HOME"] = temporary
            environment["CLAUDE_CONFIG_DIR"] = "/profiles/claude-one"
            payload = json.dumps(
                {
                    "rate_limits": {
                        "five_hour": {
                            "used_percentage": 12.5,
                            "resets_at": int(time.time()) + 3600,
                        }
                    },
                    "transcript_path": "/private/transcript.jsonl",
                }
            )

            completed = subprocess.run(
                [
                    "/usr/bin/python3",
                    "-I",
                    str(Path(collector.__file__).with_name("claude_statusline.py")),
                ],
                input=payload,
                text=True,
                capture_output=True,
                env=environment,
                timeout=5,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Claude · 5h 12%", completed.stdout)
            snapshots = list((Path(temporary) / "omarchy" / collector.PLUGIN_ID).glob("*.json"))
            self.assertEqual(len(snapshots), 1)
            self.assertNotIn("transcript", snapshots[0].read_text(encoding="utf-8"))

    def test_bridge_install_refuses_to_replace_custom_statusline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            credentials = profile / ".credentials.json"
            credentials.write_text("{}", encoding="utf-8")
            credentials.chmod(0o600)
            settings = profile / "settings.json"
            settings.write_text(
                json.dumps({"statusLine": {"type": "command", "command": "my-status"}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "already has a custom Claude status line"):
                collector.install_claude_bridge(profile)
            self.assertEqual(json.loads(settings.read_text())["statusLine"]["command"], "my-status")

    def test_bridge_install_preserves_other_user_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            credentials = profile / ".credentials.json"
            credentials.write_text("{}", encoding="utf-8")
            credentials.chmod(0o600)
            settings = profile / "settings.json"
            settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

            message = collector.install_claude_bridge(profile)
            installed = json.loads(settings.read_text(encoding="utf-8"))

            self.assertEqual(installed["theme"], "dark")
            self.assertEqual(installed["statusLine"]["type"], "command")
            self.assertIn("claude_statusline.py", installed["statusLine"]["command"])
            self.assertIn("make a Claude Code request", message)
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)

    def test_refresh_installs_claude_bridge_automatically(self) -> None:
        with temporary_cache(), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_root = root / "codex"
            codex_root.mkdir(mode=0o700)
            claude_profile = root / "claude"
            claude_profile.mkdir(mode=0o700)
            credentials = claude_profile / ".credentials.json"
            credentials.write_text("{}", encoding="utf-8")
            credentials.chmod(0o600)

            with (
                mock.patch.object(collector, "resolve_codex_command", return_value=None),
                mock.patch.object(collector, "resolve_claude_command", return_value=None),
            ):
                collector.refresh_cache(
                    codex_root,
                    force=True,
                    claude_profile_root=claude_profile,
                    claude_profile_mode="single",
                )

            installed = json.loads((claude_profile / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(installed["statusLine"]["type"], "command")
            self.assertIn("claude_statusline.py", installed["statusLine"]["command"])

    def test_automatic_bridge_setup_keeps_custom_statusline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            credentials = profile / ".credentials.json"
            credentials.write_text("{}", encoding="utf-8")
            credentials.chmod(0o600)
            settings = profile / "settings.json"
            settings.write_text(
                json.dumps({"statusLine": {"type": "command", "command": "my-status"}}),
                encoding="utf-8",
            )

            errors = collector.ensure_claude_bridges([profile])

            self.assertIn(str(profile), errors)
            self.assertEqual(json.loads(settings.read_text())["statusLine"]["command"], "my-status")


if __name__ == "__main__":
    unittest.main()
