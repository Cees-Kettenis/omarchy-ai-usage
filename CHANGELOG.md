# Changelog

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
