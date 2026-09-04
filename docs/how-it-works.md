# How AI Usage works

<p align="center">
  <img src="screenshots/summary.png" width="405" alt="Summary view showing the preferred limit for four Codex profiles">
  <img src="screenshots/details.png" width="405" alt="Profile view showing five-hour and weekly limits without account details">
</p>

Version 1.0 has one provider integration: Codex. `collector.py` fetches its
usage data and writes a small cache file. The panel asks the collector for a
validated JSON snapshot and renders the bar popup.

## Fetching usage

The collector scans one profiles folder. Each immediate subfolder is treated
as a separate `CODEX_HOME` and must contain a private `auth.json` file owned by
the current user. Symlinked profile folders and credential files are ignored
or rejected.

```text
~/.codex-profiles/
├── profile-one/
│   └── auth.json
├── profile-two/
│   └── auth.json
└── profile-three/
    └── auth.json
```

For each profile, the collector starts the installed `codex app-server` with
that folder as `CODEX_HOME` and requests its rate limits. It does not parse or
copy `auth.json`. Codex is selected from fixed install locations, checked for
safe ownership and permissions, and run with a controlled executable search
path.

The collector writes display data to:

```text
~/.cache/omarchy/ai-usage/status.json
```

`$XDG_CACHE_HOME` replaces `~/.cache` when it is set. The cache directory uses
mode `0700`, and the status file uses mode `0600`.

Cache and lock files are opened without following symlinks. Reads, writes,
profile scans, app-server replies, and display fields have size limits. Each
request and refresh also has a deadline. When a refresh ends or the widget is
destroyed, the collector stops the Codex process group it started.

## Summary and profile views

The summary shows one bar per profile. It uses the five-hour limit when one is
available and falls back to the weekly limit otherwise.

Selecting a profile shows all of its limits, reset times, credit balance, and
rate-limit resets. The popup also shows when the last successful fetch
finished.

## Settings

Open the popup and select the gear button.

<p align="center">
  <img src="screenshots/settings.png" width="413" alt="AI Usage settings for profiles, privacy, and the sleep schedule">
</p>

The settings panel controls:

- Profiles folder. Choose the parent folder that contains your Codex homes.
- Hide account details. This is on by default and keeps identity data out of
  the request and cache.
- Pause automatic checks. Set a local start and end time for the sleep window.

Sleep mode only pauses scheduled checks. The last cached result stays visible,
and manual refresh still works.

## Refresh behavior

The widget refreshes every 15 minutes by default. On startup it asks the
collector for the cached snapshot. Fetching runs separately and updates the
view when it finishes.

Use the refresh button, right-click the bar icon, or press `r` or Enter to
fetch immediately.

## Controls

- Left-click the bar icon to open or close the popup.
- Right-click or middle-click the icon to refresh.
- Use `h` and `l`, or the arrow keys, to move between tabs.
- Press `r` or Enter to refresh.
- Press Escape to close the popup.

## Command line

Print the cached result without fetching:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py --cached --print
```

Fetch now using the configured profiles folder:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py --force --print
```

Use another profiles folder for one run:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py \
  --profiles-root /path/to/profiles \
  --force \
  --print
```

Identity stays hidden unless you pass `--show-identity` explicitly.
