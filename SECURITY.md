# Security and privacy

AI Usage runs as the current desktop user. Omarchy plugins are not
sandboxed, so review the source before installing it.

The collector never parses or copies Codex `auth.json` or Claude
`.credentials.json`. It requires each profile and credential marker to be a
regular, user-owned path without symlink components. Credential files must not
be accessible to another user. It identifies providers by their distinct
marker files, then starts the matching verified CLI with that folder as
`CODEX_HOME` or `CLAUDE_CONFIG_DIR`.

Claude account discovery uses the documented `claude auth status` command.
Subscription usage is received through Claude Code's documented local status
line, not an undocumented Anthropic endpoint. The bridge keeps only usage
percentages, reset timestamps, profile location, and capture time; it discards
all other session data. Setup is opt-in and refuses to overwrite an existing
custom status line.

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

The collector uses fixed CLI install locations rather than the inherited
executable search path. It removes loader and Python injection variables from
provider environments. Claude probes also remove inherited Anthropic
credential, endpoint, and config-home overrides before setting the exact
profile location. App-server messages, command output, status-line input,
profile scans, cached data, and display strings are bounded. Requests and
refreshes have deadlines, and provider process groups are stopped on
completion, timeout, interruption, or widget destruction.

Before publishing a change, check the repository for `auth.json`, `.env`
files, access tokens, email addresses, absolute home paths, cache files, and
editor backups. The included `.gitignore` excludes the common local forms.
