#!/usr/bin/python3
"""Capture documented Claude Code status-line limits for AI Usage."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Isolated mode omits the script directory from sys.path. Add only this
# verified plugin directory so the bridge can import its sibling collector.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import collector


def main() -> int:
    try:
        raw = collector.read_statusline_input(
            sys.stdin.fileno(), time.monotonic() + collector.STATUSLINE_TIMEOUT_SECONDS
        )
        configured = os.environ.get("CLAUDE_CONFIG_DIR")
        profile_home = collector.resolve_root(configured, None, collector.DEFAULT_CLAUDE_PROFILE_ROOT)
        payload = json.loads(raw.decode("utf-8"))
        print(collector.capture_claude_statusline(payload, profile_home))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print("Claude")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
