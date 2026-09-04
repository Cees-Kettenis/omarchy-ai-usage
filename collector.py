#!/usr/bin/python3
"""Refresh and print Codex data for the AI Usage shell plugin."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import select
import secrets
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
PLUGIN_VERSION = "1.0.1"
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
MAX_PROFILES = 32
MAX_PROFILE_ENTRIES = 128
MAX_LIMITS = 8
MAX_RESETS = 16
MAX_PATH_LENGTH = 4096
DEFAULT_PROFILE_ROOT = Path.home() / ".codex-profiles"
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
SAFE_SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


class UnsafePathError(OSError):
    """Raised when a runtime path fails ownership or symlink checks."""


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)


def _file_flags() -> int:
    return os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)


def _open_directory_tree(path: Path, *, create: bool = False) -> int:
    """Open an absolute directory without following symlinks in any component."""
    path = path.expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise UnsafePathError(f"Directory must be an absolute path without '..': {path}")

    descriptor = os.open("/", _directory_flags())
    try:
        for component in path.parts[1:]:
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


def configured_profile_root() -> str | None:
    """Read the widget's profile root so the terminal alias uses the same folder."""
    try:
        config = json.loads(_read_secure_path(SHELL_CONFIG_FILE, MAX_CONFIG_BYTES).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError):
        return None

    layout = ((config.get("bar") or {}).get("layout") or {}) if isinstance(config, dict) else {}
    if not isinstance(layout, dict):
        return None
    for entries in layout.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id") != PLUGIN_ID:
                continue
            value = entry.get("profilesRoot")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def resolve_profile_root(value: str | None) -> Path:
    configured = value.strip() if isinstance(value, str) and value.strip() else configured_profile_root()
    if configured is not None and len(configured) > MAX_PATH_LENGTH:
        raise ValueError("Profiles folder path is too long")
    candidate = Path(configured).expanduser() if configured else DEFAULT_PROFILE_ROOT
    if not candidate.is_absolute():
        raise UnsafePathError("Profiles folder must be an absolute path")
    return Path(os.path.abspath(candidate))


def _trusted_executable(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    parent = _open_directory_tree(resolved.parent)
    try:
        _require_owned_directory(parent, f"Executable directory {resolved.parent}")
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


def runtime_environment(profile_home: Path, codex_command: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "BASH_ENV",
        "ENV",
        "GCONV_PATH",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
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
    env["PATH"] = os.pathsep.join((str(codex_command.parent), SAFE_SYSTEM_PATH))
    env["CODEX_HOME"] = str(profile_home)
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


def unavailable_profile(profile_home: Path, message: str) -> dict[str, Any]:
    profile_id = safe_text(profile_home.name, "Codex")
    return {
        "id": profile_id,
        "label": profile_id.replace("-", " "),
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
        auth = os.open("auth.json", os.O_RDONLY | _file_flags(), dir_fd=profile)
        try:
            _require_owned_file(auth, f"{profile_home}/auth.json", private=True)
        finally:
            os.close(auth)
    finally:
        os.close(profile)


def terminate_process_group(process: subprocess.Popen[bytes] | None) -> None:
    """Stop a Codex process and every descendant in its process group."""
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
            "id": profile_id,
            "label": profile_id.replace("-", " "),
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


def discover_profiles(profile_root: Path) -> list[Path]:
    try:
        root = _open_directory_tree(profile_root)
    except FileNotFoundError:
        return []
    try:
        _require_owned_directory(root, f"Profiles folder {profile_root}")
        names: list[str] = []
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_PROFILE_ENTRIES:
                    raise ValueError(f"Profiles folder contains more than {MAX_PROFILE_ENTRIES} entries")
                if entry.is_dir(follow_symlinks=False):
                    names.append(entry.name)
        if len(names) > MAX_PROFILES:
            raise ValueError(f"Profiles folder contains more than {MAX_PROFILES} profile directories")
        return [profile_root / name for name in sorted(names)]
    finally:
        os.close(root)


def sanitize_payload(raw: Any) -> dict[str, Any]:
    """Return a bounded cache payload containing only display fields."""
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("Unsupported cache schema")
    accounts: list[dict[str, Any]] = []
    source_accounts = raw.get("accounts")
    if not isinstance(source_accounts, list):
        raise ValueError("Cache accounts must be a list")
    for account in source_accounts[:MAX_PROFILES]:
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
        accounts.append(sanitized)
    try:
        fetched_at_ms = max(0, int(raw.get("fetchedAtMs") or 0))
    except (TypeError, ValueError):
        fetched_at_ms = 0
    return {
        "schemaVersion": SCHEMA_VERSION,
        "fetchedAt": safe_text(raw.get("fetchedAt")),
        "fetchedAtMs": fetched_at_ms,
        "profilesRoot": safe_text(raw.get("profilesRoot")),
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


def refresh_cache(profile_root: Path, force: bool = False, include_identity: bool = False) -> dict[str, Any]:
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
            if cached.get("profilesRoot") == str(profile_root) and identity_matches and 0 <= age_ms <= 45_000:
                return cached

        profiles = discover_profiles(profile_root)
        codex_command = resolve_codex_command()
        if codex_command is None:
            accounts = [unavailable_profile(profile, "Codex was not found in a trusted install location") for profile in profiles]
            global_error = "Codex was not found in a trusted install location"
        else:
            accounts_by_id: dict[str, dict[str, Any]] = {}
            if profiles:
                worker_count = min(4, len(profiles))
                executor = ThreadPoolExecutor(max_workers=worker_count)
                futures = {
                    executor.submit(probe_profile, profile, codex_command, include_identity, refresh_deadline): profile
                    for profile in profiles
                }
                try:
                    remaining = max(0.001, refresh_deadline - time.monotonic())
                    for future in as_completed(futures, timeout=remaining):
                        profile = futures[future]
                        try:
                            accounts_by_id[profile.name] = future.result()
                        except Exception as exc:  # Keep one bad profile from hiding the rest.
                            accounts_by_id[profile.name] = unavailable_profile(profile, str(exc))
                except FuturesTimeoutError:
                    pass
                finally:
                    for future, profile in futures.items():
                        if profile.name not in accounts_by_id:
                            future.cancel()
                            accounts_by_id[profile.name] = unavailable_profile(profile, "Refresh timed out")
                    executor.shutdown(wait=True, cancel_futures=True)
            accounts = [accounts_by_id[profile.name] for profile in profiles]
            global_error = "" if profiles else safe_text(f"No Codex profiles found in {profile_root}")

        now = datetime.now(timezone.utc)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "fetchedAt": now.isoformat(),
            "fetchedAtMs": int(now.timestamp() * 1000),
            "profilesRoot": str(profile_root),
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
    for account in (payload.get("accounts") or [])[:MAX_PROFILES]:
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
    parser.add_argument(
        "--show-identity",
        action="store_true",
        help="request, cache, and print account email and plan details",
    )
    parser.add_argument(
        "--profiles-root",
        metavar="PATH",
        help="folder whose immediate subdirectories are Codex homes; defaults to the widget setting",
    )
    args = parser.parse_args()
    if args.print_result and args.json_result:
        parser.error("--print and --json cannot be used together")
    profile_root = resolve_profile_root(args.profiles_root)

    try:
        payload = (
            read_cache()
            if args.cached
            else refresh_cache(profile_root, force=args.force, include_identity=args.show_identity)
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
