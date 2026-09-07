# Changelog

## 1.1.0 - 2026-09-07

### Added

- Added Claude Code account discovery through the official `claude auth
  status` command, with separate `CLAUDE_CONFIG_DIR` support for multiple
  accounts.
- Added opt-in Claude usage capture through Claude Code's documented status
  line for five-hour, seven-day, and gateway spend-limit windows.
- Added separate Codex and Claude profile locations.
- Added explicit single-account and multiple-account Claude modes, with single
  account at `~/.claude` as the default.
- Added per-profile name editing shared by the summary, profile switcher, and
  profile heading.
- Added configurable OpenAI hover/open, scheduled, and combined refresh modes
  with a one-minute default hover cooldown and configurable schedule interval.
- Grouped all scheduled and sleep controls under OpenAI, separated provider
  settings with dividers, and removed redundant popup headings.
- Matched the height of single-line settings controls and clarified that
  Claude usage setup is a one-time status-line installation.
- Removed the redundant summary logo and title, moved settings to the left,
  and aligned refresh controls through a shared label and control grid.
- Moved settings into the profile-switcher row after the final account tab.

### Security

- Kept provider discovery separate by credential marker without reading
  Claude credential contents.
- Ignored ambiguous directories containing both Codex and Claude credential
  markers.
- Removed inherited Anthropic credentials and endpoint overrides from each
  Claude probe, and refused to overwrite existing custom status lines.
- Stored only bounded, display-safe Claude limit data in owner-only cache
  files and stopped reusing expired windows.

## 1.0.1 - 2026-09-04

### Fixed

- Protected cache, lock, profile, and credential paths with no-follow,
  ownership, type, permission, and size checks.
- Replaced inherited `PATH` lookup with fixed, verified Codex install
  locations and an absolute Python interpreter.
- Added per-request, per-profile, and whole-refresh deadlines with process
  group cleanup for Codex app-server children.
- Bounded profile discovery, app-server output, cached JSON, display strings,
  and rendered account data.
- Moved cache reads out of QML and through the collector's validated JSON
  interface.
- Added focused tests for path, permission, process, RPC, and payload safety.

## 1.0.0 - 2026-09-04

### Added

- Added AI Usage, an Omarchy bar widget for viewing cached Codex usage across
  multiple local profiles.
- Added a summary that prefers the 5-hour limit and falls back to the weekly
  limit for profiles without a 5-hour window.
- Added profile views for all available limits, reset times, credits, and
  rate-limit resets.
- Added a 15-minute automatic refresh, manual refresh, last-fetch status, and
  an on-disk cache that keeps the popup responsive.
- Added configurable profile discovery with an external GTK folder picker.
- Added a configurable sleep schedule that pauses automatic checks while
  leaving manual refresh available.
- Added privacy mode, enabled by default, which skips account identity requests
  and keeps email and subscription details out of the cache.
- Added a command-line view for fetching or printing the cached status.
- Added marketplace metadata, a preview, and focused documentation for setup,
  behavior, privacy, development, and releases.
- Added tag-driven GitHub releases with installable archives and checksums.
- Required release commits to be present on the default branch and added the
  marketplace verification link to each release job summary.
