# How AI Usage works

<p align="center">
  <img src="screenshots/summary.png" width="405" alt="Summary view showing the preferred limit for multiple AI profiles">
  <img src="screenshots/details.png" width="405" alt="Profile view showing five-hour and weekly limits without account details">
</p>

Version 1.1 integrates with OpenAI Codex and Claude Code. `collector.py`
collects their display data and writes a small cache file. The panel asks the
collector for a validated JSON snapshot and renders the bar popup.

## Fetching usage

The collector scans separate Codex and Claude locations. A location may be one
profile home or a parent folder whose immediate subfolders are profile homes.
Codex profiles are identified only by `auth.json`; Claude profiles are
identified only by `.credentials.json`. This keeps one provider's profile from
being passed to the other provider's CLI. Symlinked profile folders and
credential files are ignored or rejected.

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

Claude Code keeps one account in each config home. Its documented
`CLAUDE_CONFIG_DIR` setting makes multiple accounts possible by placing each
one in a separate directory:

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

Choose `~/.claude-profiles` as **Claude location**. During refresh the
collector runs the documented `claude auth status` command once per profile
with the exact `CLAUDE_CONFIG_DIR`. It removes inherited Anthropic credential
and endpoint overrides first, so an environment variable cannot silently
select a different account or provider.

Claude Code does not expose subscription usage through a documented
non-interactive usage command. Instead, its documented status-line interface
sends `rate_limits.five_hour`, `rate_limits.seven_day`, and an optional gateway
`spend_limit` to a local command after an API response. In widget settings,
select **Enable official Claude usage capture** to add that command to every
discovered Claude profile. Existing custom status lines are never replaced.
Then make a request in each profile so Claude Code emits its current limits.

Claude Code supports one configured user status line, so this integration also
displays a compact `Claude · 5h … · 7d …` line in Claude Code. Anthropic notes
that enabling a custom status line hides most of Claude Code's footer keyboard
hints. Remove the `statusLine` field from that profile's `settings.json` before
uninstalling AI Usage, or whenever you want Claude Code's default footer back.

The bridge keeps only limit percentages, reset times, the profile location,
and capture time. It discards the rest of Claude Code's status-line input,
including transcript paths and session information. Expired windows are not
reused. The status line itself runs locally and consumes no API tokens.

Anthropic currently documents only the general five-hour and seven-day
subscription windows in this machine-readable interface. Model-specific
allowances such as Fable therefore cannot be shown separately until Claude
Code officially includes them. The parser can accept additional labeled
windows if Anthropic adds a documented list later.

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

## Settings

Open the popup and select the gear button.

<p align="center">
  <img src="screenshots/settings.png" width="413" alt="AI Usage settings for profiles, privacy, and the sleep schedule">
</p>

The settings panel controls:

- Codex location and Claude location. Keep the provider roots separate.
- Refresh behavior. Choose hover/open, scheduled, or both. Hover/open uses a
  configurable cooldown, one minute by default.
- Hide account details. This is on by default and keeps identity data out of
  the request and cache.
- Pause automatic checks. Set a local start and end time for the sleep window.

Sleep mode only pauses scheduled checks. The last cached result stays visible,
and hover/open and manual refreshes still work.

## Refresh behavior

The widget refreshes every 15 minutes by default. You can instead refresh only
when the pointer first hovers over the bar icon or the popup opens, or enable
both behaviors. Hover/open refreshes observe a configurable cooldown, one
minute by default. On startup the widget asks the collector for the cached
snapshot. Fetching runs separately and updates the view when it finishes.

A Claude refresh checks sign-in state through Claude Code and reads the most
recent locally captured usage snapshot. It does not make a model request just
to update the bar; Claude usage changes after Claude Code itself emits new
status-line data.

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
  --claude-profiles-root /path/to/claude-profiles \
  --force \
  --print
```

Enable Claude capture for every Claude profile under a location:

```bash
~/.config/omarchy/plugins/ai-usage/collector.py \
  --claude-profiles-root /path/to/claude-profiles \
  --install-claude-bridge
```

Identity stays hidden unless you pass `--show-identity` explicitly.

## Official Claude Code references

- [Status-line configuration and rate-limit fields](https://code.claude.com/docs/en/statusline)
- [Settings and `CLAUDE_CONFIG_DIR`](https://code.claude.com/docs/en/settings)
- [`claude auth status` CLI reference](https://code.claude.com/docs/en/cli-reference)
