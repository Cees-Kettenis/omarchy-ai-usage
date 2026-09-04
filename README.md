# Codex Status

A compact Omarchy bar panel for a folder of Codex profiles. It scans
`~/.codex-profiles/` by default. Each immediate subfolder is treated as a separate
`CODEX_HOME` and must contain `auth.json`.

The collector writes display-only data to
`~/.cache/omarchy/codex-status/status.json`. The panel reads that cache on
open, so it never waits for the Codex app server before showing the previous
result. It refreshes in the background every 15 minutes by default.

Sleep mode can pause automatic checks during a configurable local-time window.
It is off by default. The panel keeps showing its last cached result with a
sleep-mode banner, and manual refreshes still run during that window.

Use the gear button in the popup header to choose the profiles folder, enable
or disable privacy and sleep modes, and change both times. Privacy mode is on by
default. It skips the account identity request and caches only usage data.
Turning it off allows the collector to request and display account email and
subscription details. Saving writes the values back to the widget entry in
`~/.config/omarchy/shell.json`. Changing the profiles folder immediately
refreshes the cache from the new location.

The folder button beside the profiles path opens an external system folder
picker. Keeping it outside the shell process prevents a broken desktop portal
from taking the bar down with it. Choosing a folder fills the field; press Save
to apply it.

The Summary tab shows one bar per profile. It uses the 5-hour limit when that
profile has one, otherwise it falls back to the weekly limit. Open any profile
tab to see all of its limits and reset details.

## Controls

- Left-click the bar icon to open or close the panel.
- Right-click or middle-click the icon to refresh.
- Use `h` and `l` to move between Summary and profile tabs.
- Press `r` or Enter to refresh.
- Press Escape to close.

To print the cached result without a network fetch:

```bash
collector.py --cached --print
```

Run `codex-status` in a terminal to force a refresh and print the same data.
It reads the profiles folder from the widget settings. You can override it for
one run with `collector.py --profiles-root /path/to/profiles`. Identity remains
hidden unless you explicitly pass `--show-identity`.
