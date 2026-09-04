# Codex Status

See the Codex usage left across your local profiles from the Omarchy bar.

<p align="center">
  <img src="preview.png" width="440" alt="Codex Status summary showing usage for four profiles">
</p>

Codex Status checks each profile through the installed Codex CLI and keeps the
latest display data in a local cache. The popup opens from that cache, so it
does not wait for a network request.

## Install

Codex Status is built for Omarchy Quattro and its shell plugin system. It also
needs Python 3, the Codex CLI, and at least one signed-in Codex profile. The
folder picker uses GTK 4 and PyGObject.

Once the plugin is listed, its page on
[Omarchy Plugins](https://plugins.omarchy.org/) will provide the install
command. To install it directly from this repository, run:

```bash
omarchy plugin add https://github.com/Cees-Kettenis/omarchy-codex-status.git --enable
```

Omarchy shows the source URL, asks for confirmation, validates the manifest,
and lets you choose the bar position. This plugin has no separate installer
and does not need `sudo`.

## Update or remove

```bash
omarchy plugin update codex-status
omarchy plugin remove codex-status
```

## What you get

- One summary for every profile, with the five-hour limit preferred over the
  weekly limit.
- A detail view for each profile with all available limits and reset times.
- Automatic refresh every 15 minutes, plus a manual refresh button.
- Privacy mode that skips account identity requests and hides account details.
- A sleep schedule that pauses automatic checks without blocking manual ones.

## Documentation

- [How it works](docs/how-it-works.md) covers profiles, caching, settings,
  controls, privacy, and command-line use.
- [Development and releases](docs/development.md) covers local checks, release
  tags, archives, and the marketplace checklist.

## License

[MIT](LICENSE) © 2026 Cees Kettenis
