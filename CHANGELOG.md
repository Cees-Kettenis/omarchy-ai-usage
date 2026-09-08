# Changelog

## 1.1.0 - 2026-09-08

### Added

- Claude Code profiles alongside OpenAI Codex, with separate provider locations
  and single-account or multiple-account Claude setup.
- Opt-in Claude usage capture for five-hour, seven-day, and gateway spend-limit
  windows through Claude Code's status-line interface.
- **Enable Claude Code usage capture** and **Remove Claude Code usage capture**
  buttons beside each other in settings. Removal deletes only the matching
  command installed by AI Usage and preserves other Claude settings.
- Per-profile names shared by the summary and account tabs. Clear a name to
  restore its default without renaming the profile folder.
- OpenAI refresh on hover/open, on a schedule, or both, with a configurable
  interval and hover cooldown. Sleep pauses only scheduled OpenAI checks.
- A user guide for setup, controls, capture removal, and troubleshooting, with
  updated summary, settings, detail, and marketplace preview images.

### Changed

- Grouped settings into OpenAI, Claude, and privacy sections, with consistent
  control heights and inline refresh options.
- Placed the settings button after the account tabs and removed redundant
  headings and schedule text. The sleep banner remains visible while paused.
- Claude setup is explicit. Routine refreshes never install or change capture.
  Existing custom status lines are left unchanged and reported during setup.

### Fixed

- Folder selection now returns to settings with the selected path and other
  unsaved changes intact. Cancelling the picker preserves the draft too.
- Summary profile names no longer disappear because of a label-width binding
  loop. Long names shorten to fit beside the rename button and usage percentage.

### Security

- Rejected writable path ancestors, symlinks, ambiguous provider directories,
  and non-regular files. Nonblocking opens prevent special files from hanging
  reads; metadata-only handles validate credentials without reading them.
- Removed inherited provider credential, account, endpoint, and loader overrides.
  Provider commands start outside the inherited working directory.
- Refused hard-linked lock files before changing permissions and checked for
  concurrent Claude settings edits before replacement.
- Bounded Claude status-line input and cached display data, kept cache files
  owner-only, and stopped reusing expired usage windows.
- Pinned CI checkout code and disabled persisted checkout credentials. Release
  archives and compilation checks include the Claude bridge.

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
