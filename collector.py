#!/usr/bin/python3
"""Refresh and print provider data for the AI Usage shell plugin."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import select
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PLUGIN_VERSION = "1.1.0"
PLUGIN_ID = "ai-usage"
RPC_TIMEOUT_SECONDS = 12
PROFILE_TIMEOUT_SECONDS = 30
REFRESH_TIMEOUT_SECONDS = 45
LOCK_TIMEOUT_SECONDS = 5
MAX_TEXT_LENGTH = 256
MAX_CONFIG_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 512 * 1024
MAX_RPC_LINE_BYTES = 256 * 1024
MAX_RPC_TOTAL_BYTES = 512 * 1024
MAX_STATUSLINE_BYTES = 512 * 1024
STATUSLINE_TIMEOUT_SECONDS = 5
MAX_COMMAND_OUTPUT_BYTES = 64 * 1024
MAX_PROFILES = 32
MAX_ACCOUNTS = MAX_PROFILES * 2
MAX_PROFILE_ENTRIES = 128
MAX_LIMITS = 8
MAX_RESETS = 16
MAX_PATH_LENGTH = 4096
DEFAULT_CODEX_PROFILE_ROOT = Path.home() / ".codex-profiles"
DEFAULT_CLAUDE_PROFILE_ROOT = Path.home() / ".claude"
DEFAULT_CLAUDE_PROFILES_ROOT = Path.home() / ".claude-profiles"
SHELL_CONFIG_FILE = Path.home() / ".config" / "omarchy" / "shell.json"
CACHE_BASE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
CACHE_ROOT = CACHE_BASE / "omarchy" / "ai-usage"
CACHE_FILE = CACHE_ROOT / "status.json"
LOCK_FILE = CACHE_ROOT / "refresh.lock"
CODEX_CANDIDATES = (
    Path.home() / ".local" / "share" / "mise" / "installs" / "codex" / "latest" / "bin" / "codex",
    Path.home() / ".local" / "bin" / "codex",
    Path.home() / ".npm-global" / "bin" / "codex",
    Path("/usr/local/bin/codex"),
    Path("/usr/bin/codex"),
)
CLAUDE_CANDIDATES = (
    Path.home() / ".local" / "share" / "mise" / "installs" / "claude" / "latest" / "claude",
    Path.home() / ".local" / "bin" / "claude",
    Path.home() / ".npm-global" / "bin" / "claude",
    Path("/usr/local/bin/claude"),
    Path("/usr/bin/claude"),
)
SAFE_SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


class UnsafePathError(OSError):
    """Raised when a runtime path fails ownership or symlink checks."""


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)


def _file_flags() -> int:
    # A FIFO must not block open() before we can reject its file type.
    return os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW


def _require_trusted_directory(descriptor: int, label: str) -> None:
    details = os.fstat(descriptor)
    if details.st_uid not in (0, os.getuid()):
        raise UnsafePathError(f"{label} has an unexpected owner")
    # Root-owned sticky directories such as /tmp protect owned children
    # against replacement by other users. Other writable ancestors do not.
    sticky_root = details.st_uid == 0 and details.st_mode & stat.S_ISVTX
    if details.st_mode & 0o022 and not sticky_root:
        raise UnsafePathError(f"{label} is writable by another user")


def _open_directory_tree(path: Path, *, create: bool = False) -> int:
    """Open an absolute directory without following symlinks in any component."""
    path = path.expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise UnsafePathError(f"Directory must be an absolute path without '..': {path}")

    descriptor = os.open("/", _directory_flags())
    try:
        for component in path.parts[1:]:
            _require_trusted_directory(descriptor, f"Ancestor of {path}")
            if not component or component in (".", ".."):  # Defensive for unusual Path implementations.
                raise UnsafePathError(f"Unsafe directory component in {path}")
            try:
                child = os.open(component, _directory_flags(), dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o700, dir_fd=descriptor)
                child = os.open(component, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _require_trusted_directory(descriptor, str(path))
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _require_owned_directory(descriptor: int, label: str, *, private: bool = False) -> os.stat_result:
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        raise UnsafePathError(f"{label} is not a directory")
    if details.st_uid != os.getuid():
        raise UnsafePathError(f"{label} is not owned by the current user")
    if details.st_mode & 0o022:
        raise UnsafePathError(f"{label} is writable by another user")
    if private and details.st_mode & 0o077:
        os.fchmod(descriptor, 0o700)
    return details


def _open_private_child(parent: int, name: str) -> int:
    if not name or "/" in name or name in (".", ".."):
        raise UnsafePathError("Invalid private directory name")
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent)
    except FileNotFoundError:
        os.mkdir(name, 0o700, dir_fd=parent)
        descriptor = os.open(name, _directory_flags(), dir_fd=parent)
    try:
        _require_owned_directory(descriptor, name, private=True)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def ensure_cache_root() -> int:
    """Return an open descriptor for an owner-only, symlink-free cache directory."""
    base = _open_directory_tree(CACHE_BASE, create=True)
    try:
        _require_owned_directory(base, "Cache base")
        omarchy = _open_private_child(base, "omarchy")
    finally:
        os.close(base)
    try:
        return _open_private_child(omarchy, PLUGIN_ID)
    finally:
        os.close(omarchy)


def _require_owned_file(
    descriptor: int,
    label: str,
    *,
    private: bool = False,
    executable: bool = False,
) -> os.stat_result:
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode):
        raise UnsafePathError(f"{label} is not a regular file")
    if details.st_uid not in ({0, os.getuid()} if executable else {os.getuid()}):
        raise UnsafePathError(f"{label} has an unexpected owner")
    if details.st_mode & 0o022:
        raise UnsafePathError(f"{label} is writable by another user")
    if private and details.st_mode & 0o077:
        raise UnsafePathError(f"{label} is readable by another user")
    if executable and not details.st_mode & 0o111:
        raise UnsafePathError(f"{label} is not executable")
    return details


def _read_limited(descriptor: int, limit: int) -> bytes:
    details = os.fstat(descriptor)
    if details.st_size > limit:
        raise ValueError(f"File exceeds the {limit}-byte limit")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(65536, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise ValueError(f"File exceeds the {limit}-byte limit")


def _read_secure_path(path: Path, limit: int) -> bytes:
    parent = _open_directory_tree(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | _file_flags(), dir_fd=parent)
    finally:
        os.close(parent)
    try:
        _require_owned_file(descriptor, str(path))
        return _read_limited(descriptor, limit)
    finally:
        os.close(descriptor)


def safe_text(raw: Any, fallback: str = "", limit: int = MAX_TEXT_LENGTH) -> str:
    """Return display text without terminal or layout control characters."""
    text = str(raw if raw is not None else fallback)
    cleaned = "".join(character for character in text if character.isprintable())[:limit]
    return cleaned or str(fallback)[:limit]


def normalize_claude_profile_mode(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    return "multiple" if value in ("multiple", "multiple accounts") else "single"


def configured_provider_settings() -> tuple[str | None, str | None, str | None, str]:
    """Read provider locations and Claude mode from the widget configuration."""
    try:
        config = json.loads(_read_secure_path(SHELL_CONFIG_FILE, MAX_CONFIG_BYTES).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError):
        return None, None, None, "single"

    layout = ((config.get("bar") or {}).get("layout") or {}) if isinstance(config, dict) else {}
    if not isinstance(layout, dict):
        return None, None, None, "single"
    for entries in layout.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id") != PLUGIN_ID:
                continue
            legacy = entry.get("profilesRoot")
            codex = entry.get("codexProfilesRoot")
            claude_single = entry.get("claudeProfileRoot")
            claude_multiple = entry.get("claudeProfilesRoot")
            has_mode = isinstance(entry.get("claudeProfileMode"), str)
            mode = normalize_claude_profile_mode(entry.get("claudeProfileMode"))
            codex_value = codex if isinstance(codex, str) and codex.strip() else legacy
            # Before account modes existed, claudeProfilesRoot also represented
            # the default single ~/.claude home. Treat that value as single on
            # upgrade unless the user has explicitly chosen a mode.
            if not has_mode and not (isinstance(claude_single, str) and claude_single.strip()):
                claude_single = claude_multiple
                claude_multiple = None
            return (
                codex_value.strip() if isinstance(codex_value, str) and codex_value.strip() else None,
                claude_single.strip()
                if isinstance(claude_single, str) and claude_single.strip()
                else None,
                claude_multiple.strip()
                if isinstance(claude_multiple, str) and claude_multiple.strip()
                else None,
                mode,
            )
    return None, None, None, "single"


def resolve_root(value: str | None, configured: str | None, default: Path) -> Path:
    configured_value = value.strip() if isinstance(value, str) and value.strip() else configured
    if configured_value is not None and len(configured_value) > MAX_PATH_LENGTH:
        raise ValueError("Profiles folder path is too long")
    candidate = Path(configured_value).expanduser() if configured_value else default
    if not candidate.is_absolute():
        raise UnsafePathError("Profiles folder must be an absolute path")
    return Path(os.path.abspath(candidate))


def resolve_profile_configuration(
    codex_value: str | None,
    claude_value: str | None,
    claude_mode: str | None,
) -> tuple[Path, Path, str]:
    configured_codex, configured_single, configured_multiple, configured_mode = (
        configured_provider_settings()
    )
    mode = normalize_claude_profile_mode(claude_mode or configured_mode)
    configured_claude = configured_single if mode == "single" else configured_multiple
    default_claude = DEFAULT_CLAUDE_PROFILE_ROOT if mode == "single" else DEFAULT_CLAUDE_PROFILES_ROOT
    return (
        resolve_root(codex_value, configured_codex, DEFAULT_CODEX_PROFILE_ROOT),
        resolve_root(claude_value, configured_claude, default_claude),
        mode,
    )


def resolve_profile_roots(codex_value: str | None, claude_value: str | None) -> tuple[Path, Path]:
    """Backward-compatible provider root resolver."""
    codex_root, claude_root, _ = resolve_profile_configuration(codex_value, claude_value, None)
    return codex_root, claude_root


def resolve_profile_root(value: str | None) -> Path:
    """Backward-compatible Codex root resolver used by existing callers."""
    return resolve_profile_roots(value, None)[0]


def _trusted_executable(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    parent = _open_directory_tree(resolved.parent)
    try:
        _require_trusted_directory(parent, f"Executable directory {resolved.parent}")
        descriptor = os.open(resolved.name, os.O_RDONLY | _file_flags(), dir_fd=parent)
    finally:
        os.close(parent)
    try:
        _require_owned_file(descriptor, str(resolved), executable=True)
    finally:
        os.close(descriptor)
    return resolved


def resolve_codex_command() -> Path | None:
    """Resolve Codex from fixed install locations and reject writable targets."""
    for candidate in CODEX_CANDIDATES:
        try:
            return _trusted_executable(candidate)
        except (OSError, RuntimeError):
            continue
    return None


def resolve_claude_command() -> Path | None:
    """Resolve Claude Code from fixed install locations."""
    for candidate in CLAUDE_CANDIDATES:
        try:
            return _trusted_executable(candidate)
        except (OSError, RuntimeError):
            continue
    return None


def runtime_environment(profile_home: Path, codex_command: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "BASH_ENV",
        "ENV",
        "GCONV_PATH",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "LD_AUDIT",
        "NODE_OPTIONS",
        "NODE_PATH",
        "PERL5OPT",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "RUBYOPT",
    ):
        env.pop(key, None)
    for key in tuple(env):
        if key.startswith(("OPENAI_", "CODEX_", "ANTHROPIC_", "CLAUDE_")):
            env.pop(key, None)
    env["PATH"] = os.pathsep.join((str(codex_command.parent), SAFE_SYSTEM_PATH))
    env["CODEX_HOME"] = str(profile_home)
    return env


def claude_runtime_environment(profile_home: Path, claude_command: Path) -> dict[str, str]:
    """Build an isolated environment selecting exactly one Claude config home."""
    env = runtime_environment(profile_home, claude_command)
    env.pop("CODEX_HOME", None)
    for key in tuple(env):
        if key.startswith("ANTHROPIC_") or key in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"):
            env.pop(key, None)
    env["CLAUDE_CONFIG_DIR"] = str(profile_home)
    return env


class RpcChannel:
    """Bounded newline-delimited JSON transport for one Codex process."""

    def __init__(self, process: subprocess.Popen[bytes], deadline: float):
        if process.stdin is None or process.stdout is None:
            raise ValueError("Codex process pipes are unavailable")
        self.process = process
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.deadline = deadline
        self.buffer = bytearray()
        self.bytes_read = 0

    def _remaining(self, per_request_deadline: float) -> float:
        return min(self.deadline, per_request_deadline) - time.monotonic()

    def _next_line(self, per_request_deadline: float) -> bytes:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                if newline > MAX_RPC_LINE_BYTES:
                    raise ValueError("Codex app-server response line is too large")
                line = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                return line
            if len(self.buffer) > MAX_RPC_LINE_BYTES:
                raise ValueError("Codex app-server response line is too large")

            remaining = self._remaining(per_request_deadline)
            if remaining <= 0:
                raise TimeoutError("Codex app-server response timed out")
            ready, _, _ = select.select([self.stdout.fileno()], [], [], min(0.25, remaining))
            if not ready:
                if self.process.poll() is not None:
                    raise BrokenPipeError("Codex app-server exited before replying")
                continue

            chunk = os.read(self.stdout.fileno(), min(65536, MAX_RPC_LINE_BYTES + 1 - len(self.buffer)))
            if not chunk:
                raise BrokenPipeError("Codex app-server closed its output")
            self.bytes_read += len(chunk)
            if self.bytes_read > MAX_RPC_TOTAL_BYTES:
                raise ValueError("Codex app-server produced too much output")
            self.buffer.extend(chunk)

    def send(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > 65536:
            raise ValueError("Codex app-server request is too large")
        self.stdin.write(encoded)
        self.stdin.flush()

    def request(
        self,
        request_id: int,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.send(payload)

        request_deadline = time.monotonic() + RPC_TIMEOUT_SECONDS
        while True:
            line = self._next_line(request_deadline)
            try:
                response = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(response, dict) and response.get("id") == request_id:
                return response


def rpc_error(response: dict[str, Any], fallback: str) -> str:
    error = response.get("error")
    if isinstance(error, dict):
        return safe_text(error.get("message"), fallback)
    return ""


def pretty_plan(raw: Any) -> str:
    value = safe_text(raw).strip().lower()
    known = {
        "chatgpt_plus": "Plus",
        "plus": "Plus",
        "team": "Team",
        "business": "Business",
        "pro": "Pro",
        "free": "Free",
        "self_serve_business_prolite": "Business Pro Lite",
    }
    if value in known:
        return known[value]
    return value.replace("_", " ").title() if value else "Unknown plan"


def window_name(minutes: Any) -> str:
    try:
        duration = int(minutes)
    except (TypeError, ValueError):
        return "Usage"
    if duration == 300:
        return "5 hour"
    if duration == 10080:
        return "Weekly"
    if duration in (43200, 43800, 44640):
        return "Monthly"
    if duration > 0 and duration % 1440 == 0:
        return f"{duration // 1440} day"
    if duration > 0 and duration % 60 == 0:
        return f"{duration // 60} hour"
    return f"{duration} min" if duration > 0 else "Usage"


def normalized_limit(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        used = max(0.0, min(100.0, float(raw.get("usedPercent") or 0)))
    except (TypeError, ValueError):
        used = 0.0
    reset = raw.get("resetsAt")
    try:
        reset_at = int(reset) if reset is not None else None
    except (TypeError, ValueError):
        reset_at = None
    return {
        "name": window_name(raw.get("windowDurationMins")),
        "remainingPercent": int(100 - used),
        "usedPercent": used,
        "resetsAt": reset_at,
    }


def normalized_credits(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        remaining = max(0.0, min(100.0, float(raw.get("remainingPercent") or 0)))
    except (TypeError, ValueError):
        remaining = 0.0
    reset = raw.get("resetsAt")
    try:
        reset_at = int(reset) if reset is not None else None
    except (TypeError, ValueError):
        reset_at = None
    return {
        "remainingPercent": int(remaining),
        "used": safe_text(raw.get("used")) if raw.get("used") is not None else None,
        "limit": safe_text(raw.get("limit")) if raw.get("limit") is not None else None,
        "resetsAt": reset_at,
    }


def normalized_resets(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    credits = raw.get("credits")
    if not isinstance(credits, list):
        return []
    result = []
    for credit in credits[:MAX_RESETS]:
        if not isinstance(credit, dict) or credit.get("status") != "available":
            continue
        expires = credit.get("expiresAt")
        try:
            expires_at = int(expires) if expires is not None else None
        except (TypeError, ValueError):
            expires_at = None
        result.append(
            {
                "title": safe_text(credit.get("title"), "Rate-limit reset"),
                "expiresAt": expires_at,
            }
        )
    return result


def profile_label(profile_home: Path, provider: str) -> str:
    fallback = "Claude" if provider == "claude" else "Codex"
    raw = profile_home.name
    if raw in (".claude", ".codex"):
        return fallback
    return safe_text(raw, fallback).replace("-", " ")


def unavailable_profile(profile_home: Path, message: str, provider: str = "codex") -> dict[str, Any]:
    label = profile_label(profile_home, provider)
    return {
        "id": f"{provider}:{safe_text(profile_home.name, provider)}",
        "provider": provider,
        "providerLabel": "Claude" if provider == "claude" else "OpenAI",
        "label": label,
        "ready": False,
        "error": safe_text(message),
        "limits": [],
        "credits": None,
        "resets": [],
    }


def validate_profile(profile_home: Path) -> None:
    """Require a real, user-owned profile directory and private auth file."""
    profile = _open_directory_tree(profile_home)
    try:
        _require_owned_directory(profile, f"Profile {profile_home}")
        auth = os.open("auth.json", os.O_PATH | _file_flags(), dir_fd=profile)
        try:
            _require_owned_file(auth, f"{profile_home}/auth.json", private=True)
        finally:
            os.close(auth)
    finally:
        os.close(profile)


def validate_claude_profile(profile_home: Path) -> None:
    """Require a private Claude config home without reading its credential."""
    profile = _open_directory_tree(profile_home)
    try:
        _require_owned_directory(profile, f"Claude profile {profile_home}")
        credentials = os.open(".credentials.json", os.O_PATH | _file_flags(), dir_fd=profile)
        try:
            _require_owned_file(credentials, f"{profile_home}/.credentials.json", private=True)
        finally:
            os.close(credentials)
    finally:
        os.close(profile)


def terminate_process_group(process: subprocess.Popen[bytes] | None) -> None:
    """Stop a provider process and every descendant in its process group."""
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


_ACTIVE_PROCESSES: set[subprocess.Popen[bytes]] = set()


def _stop_active_processes(_signum: int, _frame: Any) -> None:
    for process in tuple(_ACTIVE_PROCESSES):
        terminate_process_group(process)
    raise SystemExit(128 + signal.SIGTERM)


def probe_profile(
    profile_home: Path,
    codex_command: Path,
    include_identity: bool,
    refresh_deadline: float,
) -> dict[str, Any]:
    process: subprocess.Popen[bytes] | None = None
    try:
        validate_profile(profile_home)
        if time.monotonic() >= refresh_deadline:
            raise TimeoutError("Refresh timed out")
        process = subprocess.Popen(
            [str(codex_command), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env=runtime_environment(profile_home, codex_command),
            cwd="/",
            start_new_session=True,
        )
        _ACTIVE_PROCESSES.add(process)
        channel = RpcChannel(process, min(refresh_deadline, time.monotonic() + PROFILE_TIMEOUT_SECONDS))

        initialized = channel.request(
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "omarchy_ai_usage",
                    "title": "Omarchy AI Usage",
                    "version": PLUGIN_VERSION,
                }
            },
        )
        error = rpc_error(initialized, "Codex app-server failed to initialize")
        if error:
            return unavailable_profile(profile_home, error)

        channel.send({"method": "initialized"})

        usage_response = channel.request(3, "account/rateLimits/read")

        usage_error = rpc_error(usage_response, "Failed to retrieve usage information")
        rate_result = usage_response.get("result") or {}
        rate_limits = rate_result.get("rateLimits") or {}

        limits = []
        for key in ("primary", "secondary"):
            limit = normalized_limit(rate_limits.get(key))
            if limit is not None:
                limits.append(limit)

        profile_id = safe_text(profile_home.name, "Codex")
        result = {
            "id": f"codex:{profile_id}",
            "provider": "codex",
            "providerLabel": "OpenAI",
            "label": profile_label(profile_home, "codex"),
            "ready": not bool(usage_error),
            "error": usage_error,
            "limits": limits,
            "credits": normalized_credits(rate_limits.get("individualLimit")),
            "resets": normalized_resets(rate_result.get("rateLimitResetCredits")),
        }
        if include_identity:
            account_response = channel.request(2, "account/read", {"refreshToken": False})
            account = (account_response.get("result") or {}).get("account") or {}
            result["email"] = safe_text(account.get("email"), "Unknown account")
            result["plan"] = pretty_plan(account.get("planType"))
        return result
    except (OSError, TimeoutError, BrokenPipeError, ValueError) as exc:
        return unavailable_profile(profile_home, str(exc))
    finally:
        if process is not None:
            terminate_process_group(process)
            _ACTIVE_PROCESSES.discard(process)


def _directory_has_marker(directory: int, marker: str) -> bool:
    try:
        details = os.stat(marker, dir_fd=directory, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(details.st_mode)


def discover_provider_profiles(
    profile_root: Path,
    marker: str,
    conflicting_marker: str,
    mode: str = "auto",
) -> list[Path]:
    """Find unambiguous direct or immediate-child provider homes."""
    if mode not in ("auto", "single", "multiple"):
        raise ValueError(f"Unsupported profile discovery mode: {mode}")
    try:
        root = _open_directory_tree(profile_root)
    except FileNotFoundError:
        return []
    try:
        _require_owned_directory(root, f"Profiles folder {profile_root}")
        root_matches = _directory_has_marker(root, marker)
        root_conflicts = _directory_has_marker(root, conflicting_marker)
        if root_conflicts:
            return []
        if root_matches and mode != "multiple":
            return [profile_root]
        if mode == "single" or root_matches:
            return []
        names: list[str] = []
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_PROFILE_ENTRIES:
                    raise ValueError(f"Profiles folder contains more than {MAX_PROFILE_ENTRIES} entries")
                if not entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    child = os.open(entry.name, _directory_flags(), dir_fd=root)
                except OSError:
                    continue
                try:
                    matches = _directory_has_marker(child, marker)
                    conflicts = _directory_has_marker(child, conflicting_marker)
                    if matches and not conflicts:
                        names.append(entry.name)
                finally:
                    os.close(child)
        if len(names) > MAX_PROFILES:
            raise ValueError(f"Profiles folder contains more than {MAX_PROFILES} profile directories")
        return [profile_root / name for name in sorted(names)]
    finally:
        os.close(root)


def discover_profiles(profile_root: Path) -> list[Path]:
    """Discover Codex homes while skipping directories belonging to other providers."""
    return discover_provider_profiles(profile_root, "auth.json", ".credentials.json")


def discover_claude_profiles(profile_root: Path, mode: str = "auto") -> list[Path]:
    return discover_provider_profiles(
        profile_root,
        ".credentials.json",
        "auth.json",
        normalize_claude_profile_mode(mode) if mode != "auto" else "auto",
    )


def _claude_status_name(profile_home: Path) -> str:
    digest = hashlib.sha256(str(profile_home).encode("utf-8")).hexdigest()[:24]
    return f"claude-status-{digest}.json"


def _read_private_cache_file(name: str, limit: int = MAX_STATUSLINE_BYTES) -> dict[str, Any] | None:
    directory = ensure_cache_root()
    try:
        descriptor = os.open(name, os.O_RDONLY | _file_flags(), dir_fd=directory)
        try:
            _require_owned_file(descriptor, name, private=True)
            raw = json.loads(_read_limited(descriptor, limit).decode("utf-8"))
            return raw if isinstance(raw, dict) else None
        finally:
            os.close(descriptor)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    finally:
        os.close(directory)


def _write_private_cache_file(name: str, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_STATUSLINE_BYTES:
        raise ValueError("Claude status snapshot is too large")
    directory = ensure_cache_root()
    temporary_name = f"{name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _file_flags(),
            0o600,
            dir_fd=directory,
        )
        view = memoryview(encoded)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_name, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def _used_limit(name: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        used = float(raw.get("used_percentage"))
    except (TypeError, ValueError):
        return None
    if used < 0:
        return None
    used = min(100.0, used)
    try:
        resets_at = int(raw.get("resets_at")) if raw.get("resets_at") is not None else None
    except (TypeError, ValueError):
        resets_at = None
    return {
        "name": safe_text(name, "Usage"),
        "remainingPercent": int(max(0, 100 - used)),
        "usedPercent": used,
        "resetsAt": resets_at,
    }


def normalize_claude_statusline(raw: Any, profile_home: Path) -> dict[str, Any]:
    """Keep only documented, display-safe fields from Claude Code status-line JSON."""
    if not isinstance(raw, dict):
        raise ValueError("Claude status-line input must be an object")
    rate_limits = raw.get("rate_limits")
    if not isinstance(rate_limits, dict):
        rate_limits = {}
    limits: list[dict[str, Any]] = []
    for key, name in (
        ("five_hour", "5 hour"),
        ("seven_day", "Weekly"),
        ("spend_limit", "Spend limit"),
    ):
        limit = _used_limit(name, rate_limits.get(key))
        if limit is not None:
            limits.append(limit)

    # Preserve a future documented list without assuming model names or window kinds.
    extended = rate_limits.get("limits")
    if isinstance(extended, list):
        for entry in extended[: max(0, MAX_LIMITS - len(limits))]:
            if not isinstance(entry, dict):
                continue
            label = entry.get("label") or entry.get("name") or entry.get("kind")
            limit = _used_limit(safe_text(label, "Claude usage"), entry)
            if limit is not None:
                limits.append(limit)
    return {
        "schemaVersion": 1,
        "profileRoot": str(profile_home),
        "capturedAtMs": int(time.time() * 1000),
        "limits": limits,
    }


def capture_claude_statusline(raw: Any, profile_home: Path) -> str:
    snapshot = normalize_claude_statusline(raw, profile_home)
    _write_private_cache_file(_claude_status_name(profile_home), snapshot)
    parts = []
    for limit in snapshot["limits"]:
        if limit["name"] == "5 hour":
            parts.append(f"5h {limit['usedPercent']:.0f}%")
        elif limit["name"] == "Weekly":
            parts.append(f"7d {limit['usedPercent']:.0f}%")
    return "Claude" + ((" · " + " · ".join(parts)) if parts else "")


def read_statusline_input(descriptor: int, deadline: float) -> bytes:
    """Read a bounded status-line payload without waiting indefinitely for EOF."""
    output = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Claude status-line input timed out")
        ready, _, _ = select.select([descriptor], [], [], remaining)
        if not ready:
            raise TimeoutError("Claude status-line input timed out")
        chunk = os.read(descriptor, min(65536, MAX_STATUSLINE_BYTES + 1 - len(output)))
        if not chunk:
            return bytes(output)
        output.extend(chunk)
        if len(output) > MAX_STATUSLINE_BYTES:
            raise ValueError("Claude status-line input is too large")


def _write_claude_settings(
    profile_home: Path, payload: dict[str, Any], expected: bytes | None
) -> None:
    encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_CONFIG_BYTES:
        raise ValueError("Claude settings exceed the size limit")
    directory = _open_directory_tree(profile_home)
    temporary_name = f"settings.json.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = -1
    try:
        _require_owned_directory(directory, f"Claude profile {profile_home}")
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _file_flags(),
            0o600,
            dir_fd=directory,
        )
        view = memoryview(encoded)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            current = _read_secure_path(profile_home / "settings.json", MAX_CONFIG_BYTES)
        except FileNotFoundError:
            current = None
        if current != expected:
            raise ValueError("Claude settings changed during setup; retry after saving your edits")
        os.replace(temporary_name, "settings.json", src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def install_claude_bridge(profile_home: Path) -> str:
    """Install the documented status-line bridge for one Claude profile."""
    validate_claude_profile(profile_home)
    bridge = Path(__file__).with_name("claude_statusline.py").resolve(strict=True)
    _read_secure_path(bridge, MAX_CONFIG_BYTES)
    command = f"/usr/bin/python3 -I {shlex.quote(str(bridge))}"
    settings_path = profile_home / "settings.json"
    try:
        original = _read_secure_path(settings_path, MAX_CONFIG_BYTES)
        settings = json.loads(original.decode("utf-8"))
    except FileNotFoundError:
        original = None
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError(f"{settings_path} must contain a JSON object")
    existing = settings.get("statusLine")
    desired = {"type": "command", "command": command}
    if existing == desired:
        return f"Claude usage capture is already enabled for {profile_home}"
    if existing is not None:
        raise ValueError(f"{profile_home} already has a custom Claude status line; it was not changed")
    settings["statusLine"] = desired
    _write_claude_settings(profile_home, settings, original)
    return f"Enabled Claude usage capture for {profile_home}; make a Claude Code request to populate usage"


def remove_claude_bridge(profile_home: Path) -> str:
    """Remove only this installation's status-line command."""
    settings_path = profile_home / "settings.json"
    try:
        original = _read_secure_path(settings_path, MAX_CONFIG_BYTES)
    except FileNotFoundError:
        return f"Claude usage capture is not installed for {profile_home}"
    settings = json.loads(original.decode("utf-8"))
    if not isinstance(settings, dict):
        raise ValueError(f"{settings_path} must contain a JSON object")
    bridge = Path(__file__).with_name("claude_statusline.py").resolve()
    command = f"/usr/bin/python3 -I {shlex.quote(str(bridge))}"
    existing = settings.get("statusLine")
    if existing is None:
        return f"Claude usage capture is not installed for {profile_home}"
    if existing != {"type": "command", "command": command}:
        raise ValueError(f"{profile_home} has a different Claude status line; it was not changed")
    del settings["statusLine"]
    _write_claude_settings(profile_home, settings, original)
    return f"Removed Claude usage capture for {profile_home}"


def ensure_claude_bridges(profiles: list[Path]) -> dict[str, str]:
    """Install capture where possible and report profiles that need user attention."""
    errors: dict[str, str] = {}
    for profile in profiles:
        try:
            install_claude_bridge(profile)
        except Exception as exc:
            errors[str(profile)] = safe_text(f"Claude usage capture could not be configured: {exc}")
    return errors


def setup_claude_capture(profile_root: Path, mode: str, *, remove: bool = False) -> dict[str, Any]:
    """Configure only profiles discovered during an explicit setup action."""
    directory = ensure_cache_root()
    lock = None
    try:
        lock = _open_lock(directory)
        _acquire_lock(lock, time.monotonic() + LOCK_TIMEOUT_SECONDS)
        profiles = discover_claude_profiles(profile_root, mode)
        if not profiles:
            return {"ok": False, "message": "No Claude profiles found at the saved location"}
        if remove:
            errors = {}
            for profile in profiles:
                try:
                    remove_claude_bridge(profile)
                except Exception as exc:
                    errors[str(profile)] = safe_text(f"Claude usage capture could not be removed: {exc}")
        else:
            errors = ensure_claude_bridges(profiles)
        count = len(profiles) - len(errors)
        message = f"Capture enabled for {count} Claude profile(s). Send a Claude Code message to populate usage."
        if remove:
            message = f"Capture removed or already absent for {count} Claude profile(s)."
        if errors:
            message += " " + "; ".join(errors.values())
        return {"ok": not errors, "message": safe_text(message, limit=4096)}
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def read_claude_status(profile_home: Path) -> dict[str, Any] | None:
    snapshot = _read_private_cache_file(_claude_status_name(profile_home))
    if not snapshot or snapshot.get("profileRoot") != str(profile_home):
        return None
    limits = snapshot.get("limits")
    if not isinstance(limits, list):
        return None
    sanitized_limits = []
    now = int(time.time())
    for raw in limits[:MAX_LIMITS]:
        limit = normalized_limit(raw)
        if limit is None:
            continue
        resets_at = limit.get("resetsAt")
        if resets_at is not None and resets_at <= now:
            continue
        limit["name"] = safe_text(raw.get("name"), limit["name"])
        sanitized_limits.append(limit)
    try:
        captured_at_ms = max(0, int(snapshot.get("capturedAtMs") or 0))
    except (TypeError, ValueError):
        captured_at_ms = 0
    return {"capturedAtMs": captured_at_ms, "limits": sanitized_limits}


def _bounded_process_output(process: subprocess.Popen[bytes], deadline: float) -> bytes:
    if process.stdout is None:
        raise ValueError("Process output is unavailable")
    output = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Claude Code auth status timed out")
        ready, _, _ = select.select([process.stdout.fileno()], [], [], min(0.2, remaining))
        if ready:
            chunk = os.read(process.stdout.fileno(), min(8192, MAX_COMMAND_OUTPUT_BYTES + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_COMMAND_OUTPUT_BYTES:
                raise ValueError("Claude Code auth status produced too much output")
        elif process.poll() is not None:
            break
    process.wait(timeout=max(0.01, deadline - time.monotonic()))
    return bytes(output)


def probe_claude_profile(
    profile_home: Path,
    claude_command: Path,
    include_identity: bool,
    refresh_deadline: float,
) -> dict[str, Any]:
    process: subprocess.Popen[bytes] | None = None
    try:
        validate_claude_profile(profile_home)
        if time.monotonic() >= refresh_deadline:
            raise TimeoutError("Refresh timed out")
        process = subprocess.Popen(
            [str(claude_command), "auth", "status"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env=claude_runtime_environment(profile_home, claude_command),
            cwd="/",
            start_new_session=True,
        )
        _ACTIVE_PROCESSES.add(process)
        output = _bounded_process_output(
            process,
            min(refresh_deadline, time.monotonic() + PROFILE_TIMEOUT_SECONDS),
        )
        status = json.loads(output.decode("utf-8"))
        if not isinstance(status, dict):
            raise ValueError("Claude Code returned an invalid auth status")
        logged_in = status.get("loggedIn") is True
        snapshot = read_claude_status(profile_home)
        limits = snapshot["limits"] if snapshot else []
        error = ""
        if not logged_in:
            error = "Claude Code is not signed in for this profile"
        elif snapshot is None:
            error = "Enable Claude Code usage capture in settings, then send a Claude Code message"
        elif not limits:
            error = "Claude Code has not reported subscription limits yet"
        result: dict[str, Any] = {
            "id": f"claude:{safe_text(profile_home.name, 'claude')}",
            "provider": "claude",
            "providerLabel": "Claude",
            "label": profile_label(profile_home, "claude"),
            "ready": logged_in,
            "error": error,
            "limits": limits,
            "credits": None,
            "resets": [],
            "updatedAtMs": snapshot["capturedAtMs"] if snapshot else 0,
        }
        if include_identity:
            result["email"] = safe_text(status.get("email"))
            result["plan"] = pretty_plan(status.get("subscriptionType"))
        return result
    except (OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return unavailable_profile(profile_home, str(exc), "claude")
    finally:
        if process is not None:
            terminate_process_group(process)
            _ACTIVE_PROCESSES.discard(process)


def sanitize_payload(raw: Any) -> dict[str, Any]:
    """Return a bounded cache payload containing only display fields."""
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("Unsupported cache schema")
    accounts: list[dict[str, Any]] = []
    source_accounts = raw.get("accounts")
    if not isinstance(source_accounts, list):
        raise ValueError("Cache accounts must be a list")
    for account in source_accounts[:MAX_ACCOUNTS]:
        if not isinstance(account, dict):
            continue
        limits: list[dict[str, Any]] = []
        source_limits = account.get("limits")
        if isinstance(source_limits, list):
            for limit in source_limits[:MAX_LIMITS]:
                normalized = normalized_limit(limit)
                if normalized is not None:
                    normalized["name"] = safe_text(limit.get("name"), normalized["name"])
                    limits.append(normalized)
        resets: list[dict[str, Any]] = []
        source_resets = account.get("resets")
        if isinstance(source_resets, list):
            for reset in source_resets[:MAX_RESETS]:
                if not isinstance(reset, dict):
                    continue
                try:
                    expires_at = int(reset.get("expiresAt")) if reset.get("expiresAt") is not None else None
                except (TypeError, ValueError):
                    expires_at = None
                resets.append({"title": safe_text(reset.get("title"), "Rate-limit reset"), "expiresAt": expires_at})
        sanitized: dict[str, Any] = {
            "id": safe_text(account.get("id"), "Codex"),
            "label": safe_text(account.get("label") or account.get("id"), "Codex"),
            "provider": safe_text(account.get("provider"), "codex"),
            "providerLabel": safe_text(account.get("providerLabel"), "OpenAI"),
            "ready": account.get("ready") is True,
            "error": safe_text(account.get("error")),
            "limits": limits,
            "credits": normalized_credits(account.get("credits")),
            "resets": resets,
        }
        if isinstance(account.get("email"), str):
            sanitized["email"] = safe_text(account["email"])
        if isinstance(account.get("plan"), str):
            sanitized["plan"] = safe_text(account["plan"])
        try:
            sanitized["updatedAtMs"] = max(0, int(account.get("updatedAtMs") or 0))
        except (TypeError, ValueError):
            sanitized["updatedAtMs"] = 0
        accounts.append(sanitized)
    try:
        fetched_at_ms = max(0, int(raw.get("fetchedAtMs") or 0))
    except (TypeError, ValueError):
        fetched_at_ms = 0
    return {
        "schemaVersion": SCHEMA_VERSION,
        "fetchedAt": safe_text(raw.get("fetchedAt")),
        "fetchedAtMs": fetched_at_ms,
        "profilesRoot": safe_text(raw.get("profilesRoot") or raw.get("codexProfilesRoot")),
        "codexProfilesRoot": safe_text(raw.get("codexProfilesRoot") or raw.get("profilesRoot")),
        "claudeProfilesRoot": safe_text(raw.get("claudeProfilesRoot")),
        "claudeProfileMode": normalize_claude_profile_mode(raw.get("claudeProfileMode")),
        "includesIdentity": raw.get("includesIdentity") is True,
        "error": safe_text(raw.get("error")),
        "accounts": accounts,
    }


def redact_identity(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = sanitize_payload(payload)
    redacted["includesIdentity"] = False
    for account in redacted["accounts"]:
        account.pop("email", None)
        account.pop("plan", None)
    return redacted


def _read_cache_from(directory: int) -> dict[str, Any]:
    descriptor = os.open(CACHE_FILE.name, os.O_RDONLY | _file_flags(), dir_fd=directory)
    try:
        _require_owned_file(descriptor, str(CACHE_FILE), private=True)
        raw = json.loads(_read_limited(descriptor, MAX_CACHE_BYTES).decode("utf-8"))
        return sanitize_payload(raw)
    finally:
        os.close(descriptor)


def _open_lock(directory: int) -> int:
    descriptor = os.open(
        LOCK_FILE.name,
        os.O_RDWR | os.O_CREAT | _file_flags(),
        0o600,
        dir_fd=directory,
    )
    try:
        _require_owned_file(descriptor, str(LOCK_FILE))
        if os.fstat(descriptor).st_nlink != 1:
            raise UnsafePathError("Refresh lock must not have hard links")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _acquire_lock(descriptor: int, deadline: float) -> None:
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for another refresh")
            time.sleep(0.05)


def write_cache(payload: dict[str, Any], directory: int | None = None) -> None:
    owned_directory = directory is None
    if directory is None:
        directory = ensure_cache_root()
    temporary_name = ""
    descriptor = -1
    try:
        encoded = (json.dumps(sanitize_payload(payload), indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_CACHE_BYTES:
            raise ValueError("Cache payload is too large")
        temporary_name = f"status.json.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _file_flags(),
            0o600,
            dir_fd=directory,
        )
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_name, CACHE_FILE.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
        if owned_directory:
            os.close(directory)


def refresh_cache(
    profile_root: Path,
    force: bool = False,
    include_identity: bool = False,
    claude_profile_root: Path | None = None,
    claude_profile_mode: str = "single",
) -> dict[str, Any]:
    codex_profile_root = profile_root
    claude_profile_root = claude_profile_root or DEFAULT_CLAUDE_PROFILE_ROOT
    claude_profile_mode = normalize_claude_profile_mode(claude_profile_mode)
    refresh_deadline = time.monotonic() + REFRESH_TIMEOUT_SECONDS
    directory = ensure_cache_root()
    lock: int | None = None
    try:
        lock = _open_lock(directory)
        _acquire_lock(lock, min(refresh_deadline, time.monotonic() + LOCK_TIMEOUT_SECONDS))

        # Omarchy creates one bar widget per monitor. Their timers normally
        # fire together, so the second process reuses the result that the
        # first one just wrote instead of probing every account twice.
        if not force:
            cached = read_cache(directory)
            fetched_at_ms = int(cached.get("fetchedAtMs") or 0)
            age_ms = int(time.time() * 1000) - fetched_at_ms
            identity_matches = cached.get("includesIdentity") is include_identity
            roots_match = (
                cached.get("codexProfilesRoot") == str(codex_profile_root)
                and cached.get("claudeProfilesRoot") == str(claude_profile_root)
                and cached.get("claudeProfileMode") == claude_profile_mode
            )
            if roots_match and identity_matches and 0 <= age_ms <= 45_000:
                return cached

        codex_profiles = discover_profiles(codex_profile_root)
        claude_profiles = discover_claude_profiles(claude_profile_root, claude_profile_mode)
        codex_command = resolve_codex_command()
        claude_command = resolve_claude_command()
        accounts_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        jobs: list[tuple[str, Path, Any, Path]] = []
        if codex_command is None:
            for profile in codex_profiles:
                accounts_by_key[("codex", str(profile))] = unavailable_profile(
                    profile, "Codex was not found in a trusted install location"
                )
        else:
            jobs.extend(("codex", profile, probe_profile, codex_command) for profile in codex_profiles)
        if claude_command is None:
            for profile in claude_profiles:
                accounts_by_key[("claude", str(profile))] = unavailable_profile(
                    profile, "Claude Code was not found in a trusted install location", "claude"
                )
        else:
            jobs.extend(("claude", profile, probe_claude_profile, claude_command) for profile in claude_profiles)

        if jobs:
            worker_count = min(4, len(jobs))
            executor = ThreadPoolExecutor(max_workers=worker_count)
            futures = {
                executor.submit(probe, profile, command, include_identity, refresh_deadline): (provider, profile)
                for provider, profile, probe, command in jobs
            }
            try:
                remaining = max(0.001, refresh_deadline - time.monotonic())
                for future in as_completed(futures, timeout=remaining):
                    provider, profile = futures[future]
                    try:
                        accounts_by_key[(provider, str(profile))] = future.result()
                    except Exception as exc:  # Keep one bad profile from hiding the rest.
                        accounts_by_key[(provider, str(profile))] = unavailable_profile(profile, str(exc), provider)
            except FuturesTimeoutError:
                pass
            finally:
                for future, (provider, profile) in futures.items():
                    key = (provider, str(profile))
                    if key not in accounts_by_key:
                        future.cancel()
                        accounts_by_key[key] = unavailable_profile(profile, "Refresh timed out", provider)
                executor.shutdown(wait=True, cancel_futures=True)

        accounts = [accounts_by_key[("codex", str(profile))] for profile in codex_profiles]
        for profile in claude_profiles:
            account = accounts_by_key[("claude", str(profile))]
            accounts.append(account)
        global_error = ""
        if not accounts:
            global_error = safe_text(
                f"No Codex profiles found in {codex_profile_root} and no Claude profiles found in {claude_profile_root}"
            )

        now = datetime.now(timezone.utc)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "fetchedAt": now.isoformat(),
            "fetchedAtMs": int(now.timestamp() * 1000),
            "profilesRoot": str(codex_profile_root),
            "codexProfilesRoot": str(codex_profile_root),
            "claudeProfilesRoot": str(claude_profile_root),
            "claudeProfileMode": claude_profile_mode,
            "includesIdentity": include_identity,
            "error": global_error,
            "accounts": accounts,
        }
        write_cache(payload, directory)
        return payload
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def read_cache(directory: int | None = None) -> dict[str, Any]:
    owned_directory = directory is None
    try:
        if directory is None:
            directory = ensure_cache_root()
        return _read_cache_from(directory)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError):
        return {"schemaVersion": SCHEMA_VERSION, "accounts": [], "error": "No cached result yet"}
    finally:
        if owned_directory and directory is not None:
            os.close(directory)


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "now"
    minutes = seconds // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{max(1, minutes)}m"


def usage_bar(remaining: int, width: int = 20) -> str:
    filled = max(0, min(width, remaining * width // 100))
    return "█" * filled + "░" * (width - filled)


def print_payload(payload: dict[str, Any], show_identity: bool = False) -> None:
    fetched_at_ms = int(payload.get("fetchedAtMs") or 0)
    fetched = datetime.fromtimestamp(fetched_at_ms / 1000).astimezone() if fetched_at_ms else None
    print("\n  AI USAGE DASHBOARD")
    if fetched:
        print(f"  Last fetched {fetched:%A, %d %B %Y  %H:%M:%S}\n")
    else:
        print("  No cached result yet\n")

    error = safe_text(payload.get("error"))
    if error:
        print(f"  {error}\n")

    now = int(time.time())
    for account in (payload.get("accounts") or [])[:MAX_ACCOUNTS]:
        label = safe_text(account.get("label") or account.get("id"), "Codex")
        print(f"╭─ {label}")
        if show_identity:
            identity = "  •  ".join(
                safe_text(part) for part in (account.get("email"), account.get("plan")) if part
            )
            if identity:
                print(f"│  {identity}")
        if account.get("error"):
            print(f"│  {safe_text(account['error'])}")

        for limit in (account.get("limits") or [])[:MAX_LIMITS]:
            remaining = int(limit.get("remainingPercent") or 0)
            reset = limit.get("resetsAt")
            reset_text = f"  reset in {format_duration(int(reset) - now)}" if reset else ""
            name = safe_text(limit.get("name"), "Usage")
            print(f"│  {name:<16} {usage_bar(remaining)}  {remaining:3d}% left{reset_text}")

        credits = account.get("credits")
        if credits:
            remaining = int(credits.get("remainingPercent") or 0)
            print(f"│  {'Monthly credits':<16} {usage_bar(remaining)}  {remaining:3d}% left")
            if credits.get("used") is not None and credits.get("limit") is not None:
                used = safe_text(credits["used"])
                limit = safe_text(credits["limit"])
                print(f"│  {'':<16} {used} / {limit} used")

        resets = account.get("resets") or []
        if resets:
            print(f"│  Reset available: {len(resets)}")
        print("╰───────────────────────────────────────────────────────────\n")


def main() -> int:
    signal.signal(signal.SIGTERM, _stop_active_processes)
    signal.signal(signal.SIGINT, _stop_active_processes)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="print_result", help="print the cached dashboard")
    parser.add_argument("--json", action="store_true", dest="json_result", help="write the bounded JSON result")
    parser.add_argument("--cached", action="store_true", help="do not refresh before printing")
    parser.add_argument("--force", action="store_true", help="refresh even when another monitor just updated the cache")
    capture_actions = parser.add_mutually_exclusive_group()
    capture_actions.add_argument(
        "--setup-claude-capture", action="store_true",
        help="explicitly add the local status-line command to the selected Claude profiles",
    )
    capture_actions.add_argument(
        "--remove-claude-capture", action="store_true",
        help="remove this plugin's status-line command from the selected Claude profiles",
    )
    parser.add_argument(
        "--show-identity",
        action="store_true",
        help="request, cache, and print account email and plan details",
    )
    parser.add_argument(
        "--profiles-root",
        metavar="PATH",
        help="deprecated alias for --codex-profiles-root",
    )
    parser.add_argument(
        "--codex-profiles-root",
        metavar="PATH",
        help="Codex home or folder whose immediate subdirectories are Codex homes",
    )
    parser.add_argument(
        "--claude-profiles-root",
        metavar="PATH",
        help="Claude config home in single mode or parent folder in multiple mode",
    )
    parser.add_argument(
        "--claude-profile-mode",
        choices=("single", "multiple"),
        help="treat the Claude location as one config home or a parent of config homes",
    )
    args = parser.parse_args()
    if args.print_result and args.json_result:
        parser.error("--print and --json cannot be used together")
    if args.profiles_root and args.codex_profiles_root:
        parser.error("--profiles-root and --codex-profiles-root cannot be used together")
    if (args.setup_claude_capture or args.remove_claude_capture) and (args.cached or args.force or args.print_result or args.show_identity):
        parser.error("capture setup/removal supports --json and profile selection only")
    codex_value = args.codex_profiles_root or args.profiles_root
    codex_profile_root, claude_profile_root, claude_profile_mode = resolve_profile_configuration(
        codex_value, args.claude_profiles_root, args.claude_profile_mode
    )

    if args.setup_claude_capture or args.remove_claude_capture:
        try:
            result = setup_claude_capture(claude_profile_root, claude_profile_mode, remove=args.remove_claude_capture)
        except (OSError, ValueError) as exc:
            result = {"ok": False, "message": safe_text(f"Claude capture action failed: {exc}")}
        print(json.dumps(result) if args.json_result else result["message"])
        return 0 if result["ok"] else 1

    try:
        payload = (
            read_cache()
            if args.cached
            else refresh_cache(
                codex_profile_root,
                force=args.force,
                include_identity=args.show_identity,
                claude_profile_root=claude_profile_root,
                claude_profile_mode=claude_profile_mode,
            )
        )
    except Exception as exc:
        print(f"ai-usage: refresh failed: {exc}", file=sys.stderr)
        payload = read_cache()
        if not (args.print_result or args.json_result):
            return 1

    if not args.show_identity:
        payload = redact_identity(payload)

    if args.print_result:
        print_payload(payload, show_identity=args.show_identity)
    elif args.json_result:
        print(json.dumps(sanitize_payload(payload), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
