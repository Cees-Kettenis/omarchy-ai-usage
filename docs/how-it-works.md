# How AI Usage works

<p align="center">
  <img src="screenshots/summary.png" width="405" alt="Summary view showing the preferred limit for multiple AI profiles">
  <img src="screenshots/details.png" width="405" alt="Profile view showing five-hour and weekly limits without account details">
</p>

For setup and everyday controls, start with the [user guide](user-guide.md).

Version 1.1 integrates with OpenAI Codex and Claude Code. `collector.py`
collects their display data and writes a small cache file. The panel asks the
collector for a validated JSON snapshot and renders the bar popup.

## Fetching usage

The collector scans separate OpenAI and Claude locations. Codex profiles use
`auth.json`; Claude profiles use `.credentials.json`. A directory containing
both markers is ambiguous, so the collector ignores it for both providers.
Symlinked profile folders and credential files are ignored or rejected.

### Codex profiles

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

### Claude profiles

Claude defaults to single-account mode and uses `~/.claude` directly. Claude
Code keeps one account in each config home. Its documented `CLAUDE_CONFIG_DIR`
setting makes multiple accounts possible by placing each one in a separate
directory:

```text
~/.claude-profiles/
├── personal/
│   └── .credentials.json
└── work/
    └── .credentials.json
```

Launch or sign in to each account with its own location, for example:

```bash
CLAUDE_CONFIG_DIR=~/.claude-profiles/personal claude auth login
CLAUDE_CONFIG_DIR=~/.claude-profiles/work claude auth login
```

Choose **Multiple accounts**, then choose `~/.claude-profiles` as the parent
location. Multiple-account mode scans immediate subfolders only; single mode
checks only the configured home. During refresh the collector runs the
documented `claude auth status` command once per profile with the exact
`CLAUDE_CONFIG_DIR`. It removes inherited Anthropic credential and endpoint
overrides first, so an environment variable cannot silently select a different
account or provider.

Claude Code does not expose subscription usage through a documented
non-interactive usage command. Instead, its documented status-line interface
sends `rate_limits.five_hour`, `rate_limits.seven_day`, and an optional gateway
`spend_limit` to a local command after an API response. Save your profile
locations, then click **Enable Claude Code usage capture** in settings.
This adds the command to the saved profiles that exist at that moment. Existing
custom status lines are preserved, and capture is not installed for those
profiles. Routine refreshes never change Claude
settings. Repeat setup after adding profiles, and make a request in each profile
so Claude Code emits its current limits.

Claude Code supports one configured user status line, so this integration also
displays a compact `Claude · 5h … · 7d …` line in Claude Code. Anthropic notes
that enabling a custom status line hides most of Claude Code's footer keyboard
hints. Click **Remove Claude Code usage capture** before uninstalling AI Usage, or
whenever you want Claude Code's default footer back. This removes capture from
the saved Claude location and leaves other status-line commands unchanged.
The command-line equivalent is `collector.py --remove-claude-capture`.

The bridge keeps only limit percentages, reset times, the profile location,
and capture time. It discards the rest of Claude Code's status-line input,
including transcript paths and session information. Expired windows are not
reused. The status line itself runs locally and consumes no API tokens.

AI Usage can show only the limits supplied by Claude Code's status-line payload.
It cannot derive missing model-specific allowances from the general windows.

## Local cache

The collector writes display data to:

```text
~/.cache/omarchy/ai-usage/status.json
```

`$XDG_CACHE_HOME` replaces `~/.cache` when it is set. The cache directory uses
mode `0700`, and the status file uses mode `0600`.

Cache and lock files are opened without following symlinks. Reads, writes,
profile scans, provider output, and display fields have size limits. Each
request and refresh also has a deadline. When a refresh ends or the widget is
destroyed, the collector stops every provider process group it started.

## Summary and profile views

The summary shows one bar per profile. It uses the five-hour limit when one is
available and falls back to the weekly limit otherwise.

Selecting a profile shows all of its limits, reset times, credit balance, and
rate-limit resets. The popup shows when the last fetch finished. Claude
profiles also show when Claude Code last emitted their usage snapshot.

Profile names normally come from their folders. The pencil beside each summary
name edits that profile only. Saved names apply to the summary, profile
switcher, and profile heading without renaming folders or changing credentials.

## Settings

Open the popup and select the gear button.

<p align="center">
  <img src="screenshots/settings.png" width="396" alt="OpenAI and Claude settings with side-by-side capture enable and remove buttons">
</p>

The settings panel controls:

- OpenAI location, API refresh behavior, and sleep schedule. Choose hover/open,
  scheduled, or both. The schedule interval and hover cooldown are
  configurable. Sleep only pauses scheduled OpenAI checks.
- Claude account setup, with separate single-account and multiple-account
  locations. Single account is the default. Save the location before using the
  capture enable or remove buttons.
- Hide account details. This is on by default and keeps identity data out of
  the request and cache.

Selecting a folder temporarily hides the popup. It returns to settings when
the picker finishes, keeping the selected path and other unsaved edits.
Cancelling the picker keeps the previous path. Click **Save** to apply changes.

The settings UI groups sleep with OpenAI and separates the provider sections
with a line. Privacy is the only global setting. When sleep is active, the last
cached result stays visible, and hover/open and manual refreshes still work.

## Refresh behavior

The widget fetches OpenAI usage every 15 minutes by default. You can change the
interval, fetch only when the pointer first hovers over the bar icon or the
popup opens, or enable both behaviors. Hover/open fetches observe a
configurable cooldown, one minute by default. On startup the widget asks the
collector for the cached snapshot. Fetching runs separately and updates the
view when it finishes.

These settings control OpenAI API requests. Claude usage only changes after
Claude Code emits new data through its official status line following a
message. When the collector runs, it checks Claude sign-in state and reads the
latest local snapshot. It never makes a model request just to update the bar.

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

Fetch now using the configured profile locations:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py --force --print
```

Use other profile locations for one run:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py \
  --codex-profiles-root /path/to/codex-profiles \
  --claude-profiles-root /path/to/one-claude-home \
  --claude-profile-mode single \
  --force \
  --print
```

Configure capture explicitly from the command line:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py --setup-claude-capture
```

Remove capture before uninstalling:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py --remove-claude-capture
```

Both capture commands accept the same Claude profile location and mode options.
They operate on the selected location and do not run provider commands.
Removal checks for the exact command installed by this copy of AI Usage before
deleting the status-line setting. Other settings and custom status lines remain.
Disabling or uninstalling the widget does not perform this cleanup automatically.
Previously configured locations must be selected separately for removal.

Identity stays hidden unless you pass `--show-identity` explicitly.

## Official Claude Code references

- [Status-line configuration and rate-limit fields](https://code.claude.com/docs/en/statusline)
- [Settings and `CLAUDE_CONFIG_DIR`](https://code.claude.com/docs/en/settings)
- [`claude auth status` CLI reference](https://code.claude.com/docs/en/cli-reference)
