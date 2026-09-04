# Security and privacy

AI Usage runs as the current desktop user. Omarchy plugins are not
sandboxed, so review the source before installing it.

The collector never parses or copies `auth.json`. It requires the profile and
credential file to be regular, user-owned paths without symlink components.
The credential file must not be accessible to another user. It then starts a
verified Codex executable with that folder as `CODEX_HOME`.

Privacy mode is enabled by default. In that mode, the collector does not call
the account identity endpoint and does not write email or subscription details
to its cache. Turning privacy mode off allows those fields to be requested and
cached. Cached JSON output also removes identity fields unless
`--show-identity` is passed explicitly.

Runtime data is written outside the plugin repository under
`$XDG_CACHE_HOME/omarchy/ai-usage/`, or `~/.cache/omarchy/ai-usage/`
when `XDG_CACHE_HOME` is unset. The cache directory uses mode `0700`, and the
status and lock files use mode `0600`. Every path component is opened without
following symlinks. Cache writes use a private, exclusive temporary file and
an atomic replacement.

The collector uses fixed Codex install locations rather than the inherited
executable search path. It removes loader and Python injection variables from
the Codex environment. App-server messages, profile scans, cached data, and
display strings are bounded. Requests and refreshes have deadlines, and Codex
process groups are stopped on completion, timeout, interruption, or widget
destruction.

Before publishing a change, check the repository for `auth.json`, `.env`
files, access tokens, email addresses, absolute home paths, cache files, and
editor backups. The included `.gitignore` excludes the common local forms.
