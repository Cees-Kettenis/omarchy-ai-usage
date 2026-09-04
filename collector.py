#!/usr/bin/env python3
"""Refresh and print Codex data for the AI Usage shell plugin."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
RPC_TIMEOUT_SECONDS = 12
PLUGIN_ID = "ai-usage"
DEFAULT_PROFILE_ROOT = Path.home() / ".codex-profiles"
SHELL_CONFIG_FILE = Path.home() / ".config" / "omarchy" / "shell.json"
CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "omarchy" / "ai-usage"
CACHE_FILE = CACHE_ROOT / "status.json"
LOCK_FILE = CACHE_ROOT / "refresh.lock"


def safe_text(raw: Any, fallback: str = "") -> str:
    """Return display text without terminal or layout control characters."""
    text = str(raw if raw is not None else fallback)
    cleaned = "".join(character for character in text if character.isprintable())
    return cleaned or fallback


def ensure_cache_root() -> None:
    CACHE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    CACHE_ROOT.chmod(0o700)


def configured_profile_root() -> str | None:
    """Read the widget's profile root so the terminal alias uses the same folder."""
    try:
        config = json.loads(SHELL_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, AttributeError):
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
    return Path(configured).expanduser() if configured else DEFAULT_PROFILE_ROOT


def runtime_environment(profile_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    path_parts = [
        env.get("PATH", ""),
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".npm-global" / "bin"),
        str(Path.home() / ".local" / "share" / "mise" / "shims"),
    ]
    env["PATH"] = os.pathsep.join(part for part in path_parts if part)
    env["CODEX_HOME"] = str(profile_home)
    return env


def rpc_request(
    process: subprocess.Popen[str],
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert process.stdin is not None
    assert process.stdout is not None

    payload: dict[str, Any] = {"id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()

    deadline = time.monotonic() + RPC_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.25)
        if not ready:
            if process.poll() is not None:
                break
            continue

        line = process.stdout.readline()
        if not line:
            break
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if response.get("id") == request_id:
            return response

    raise TimeoutError(f"Codex app-server timed out during {method}")


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
        "used": raw.get("used"),
        "limit": raw.get("limit"),
        "resetsAt": reset_at,
    }


def normalized_resets(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    credits = raw.get("credits")
    if not isinstance(credits, list):
        return []
    result = []
    for credit in credits:
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


def probe_profile(profile_home: Path, codex_command: str, include_identity: bool) -> dict[str, Any]:
    if not (profile_home / "auth.json").is_file():
        return unavailable_profile(profile_home, "No auth.json found")

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [codex_command, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=runtime_environment(profile_home),
        )

        initialized = rpc_request(
            process,
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "omarchy_ai_usage",
                    "title": "Omarchy AI Usage",
                    "version": "1.0.0",
                }
            },
        )
        error = rpc_error(initialized, "Codex app-server failed to initialize")
        if error:
            return unavailable_profile(profile_home, error)

        assert process.stdin is not None
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()

        usage_response = rpc_request(process, 3, "account/rateLimits/read")

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
            account_response = rpc_request(process, 2, "account/read", {"refreshToken": False})
            account = (account_response.get("result") or {}).get("account") or {}
            result["email"] = safe_text(account.get("email"), "Unknown account")
            result["plan"] = pretty_plan(account.get("planType"))
        return result
    except (OSError, TimeoutError, BrokenPipeError) as exc:
        return unavailable_profile(profile_home, str(exc))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def discover_profiles(profile_root: Path) -> list[Path]:
    if not profile_root.is_dir():
        return []
    return sorted((path for path in profile_root.iterdir() if path.is_dir()), key=lambda path: path.name)


def write_cache(payload: dict[str, Any]) -> None:
    ensure_cache_root()
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=CACHE_ROOT,
        prefix="status.json.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        temporary_path.chmod(0o600)
        temporary_path.replace(CACHE_FILE)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def refresh_cache(profile_root: Path, force: bool = False, include_identity: bool = False) -> dict[str, Any]:
    ensure_cache_root()
    with LOCK_FILE.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        # Omarchy creates one bar widget per monitor. Their timers normally
        # fire together, so the second process reuses the result that the
        # first one just wrote instead of probing every account twice.
        if not force:
            cached = read_cache()
            fetched_at_ms = int(cached.get("fetchedAtMs") or 0)
            age_ms = int(time.time() * 1000) - fetched_at_ms
            identity_matches = cached.get("includesIdentity") is include_identity
            if cached.get("profilesRoot") == str(profile_root) and identity_matches and 0 <= age_ms <= 45_000:
                return cached

        profiles = discover_profiles(profile_root)
        codex_command = shutil.which("codex")
        if codex_command is None:
            accounts = [unavailable_profile(profile, "codex was not found in PATH") for profile in profiles]
            global_error = "codex was not found in PATH"
        else:
            accounts_by_id: dict[str, dict[str, Any]] = {}
            worker_count = max(1, min(4, len(profiles)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(probe_profile, profile, codex_command, include_identity): profile
                    for profile in profiles
                }
                for future in as_completed(futures):
                    profile = futures[future]
                    try:
                        accounts_by_id[profile.name] = future.result()
                    except Exception as exc:  # Keep one bad profile from hiding the rest.
                        accounts_by_id[profile.name] = unavailable_profile(profile, str(exc))
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
        write_cache(payload)
        return payload


def read_cache() -> dict[str, Any]:
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if payload.get("schemaVersion") == SCHEMA_VERSION:
            return payload
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return {"schemaVersion": SCHEMA_VERSION, "accounts": [], "error": "No cached result yet"}


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
    for account in payload.get("accounts") or []:
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

        for limit in account.get("limits") or []:
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="print_result", help="print the cached dashboard")
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
        if not args.print_result:
            return 1

    if args.print_result:
        print_payload(payload, show_identity=args.show_identity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
