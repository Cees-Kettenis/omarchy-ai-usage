# AI Usage

See the AI usage left across your local profiles from the Omarchy bar.

<p align="center">
  <img src="preview.png" width="440" alt="AI Usage summary showing usage for four profiles">
</p>

Version 1.1 supports OpenAI Codex and Claude Code profiles. AI Usage checks
each profile through its installed official CLI and keeps the latest display
data in a local cache. The popup opens from that cache, so it does not wait for
a network request. Kimi and Grok are not supported yet.

## Install

AI Usage is built for Omarchy Quattro and its shell plugin system. It also
needs Python 3 and at least one supported, signed-in CLI profile. Install the
Codex CLI for OpenAI profiles and Claude Code for Claude profiles. The folder
picker uses GTK 4 and PyGObject.

Once the plugin is listed, its page on
[Omarchy Plugins](https://plugins.omarchy.org/) will provide the install
command. To install it directly from this repository, run:

```bash
omarchy plugin add https://github.com/Cees-Kettenis/omarchy-ai-usage.git --enable
```

Omarchy shows the source URL, asks for confirmation, validates the manifest,
and lets you choose the bar position. This plugin has no separate installer
and does not request elevated privileges.

## Update or remove

```bash
omarchy plugin update ai-usage
omarchy plugin remove ai-usage
```

## What you get

- One summary for every OpenAI and Claude profile, with the five-hour limit
  preferred over the weekly limit.
- A detail view for each profile with all available limits and reset times.
- Refresh on hover/open, on a schedule, or both, plus a manual refresh button.
- A configurable cooldown that prevents accidental repeated hover refreshes.
- Privacy mode that skips account identity requests and hides account details.
- A sleep schedule that pauses automatic checks without blocking manual ones.

## Claude setup

Set **Claude location** to `~/.claude` for one account, or to a parent folder
whose immediate children are separate `CLAUDE_CONFIG_DIR` homes. Then select
**Enable official Claude usage capture** in the widget settings and make a
request in each Claude Code profile.

Claude Code sends the documented five-hour and seven-day subscription windows
to the plugin's local status-line command. The command does not use API tokens,
and the collector uses the documented `claude auth status` command to check
which account is signed in. AI Usage does not read Claude credential contents
or call an undocumented Anthropic endpoint.

If a Claude profile already has a custom status line, setup leaves it unchanged
instead of overwriting it. Enabling capture also displays a compact usage line
inside Claude Code. See [How it works](docs/how-it-works.md) for manual setup,
status-line tradeoffs, and multi-account examples.

## Documentation

- [How it works](docs/how-it-works.md) covers profiles, caching, settings,
  controls, privacy, and command-line use.
- [Development and releases](docs/development.md) covers local checks, release
  tags, archives, and the marketplace checklist.

## License

[MIT](LICENSE) © 2026 Cees Kettenis
