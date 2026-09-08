# Security and privacy

AI Usage runs as the current desktop user. Omarchy plugins are not
sandboxed, so review the source before installing it.

The collector never parses or copies Codex `auth.json` or Claude
`.credentials.json`. It requires each profile and credential marker to be a
regular, user-owned path without symlink components. Credential files must not
be accessible to another user. Discovery uses file metadata, and validation
uses Linux metadata-only handles that cannot read credential contents.
It identifies providers by their distinct
marker files, then starts the matching permission-checked CLI with that folder as
`CODEX_HOME` or `CLAUDE_CONFIG_DIR`.

If one directory contains both provider markers, the collector ignores it for
both providers. Single-account Claude discovery never scans children, while
multiple-account discovery only scans immediate children of its configured
parent.

Claude account discovery uses the documented `claude auth status` command.
Subscription usage is received through Claude Code's documented local status
line, not an undocumented Anthropic endpoint. The bridge keeps only usage
percentages, reset timestamps, profile location, and capture time; it discards
all other session data. The collector installs the bridge only through the explicit
Enable Claude Code usage capture action or `--setup-claude-capture` command. Routine
refreshes never write Claude settings. Setup preserves an existing custom
status line and reports that capture could not be installed for that profile.
Use **Remove Claude Code usage capture** or `--remove-claude-capture` before
uninstalling. Removal checks for this installation's exact status-line command,
preserves other settings, and refuses to replace a concurrently changed file.
It operates on the selected profile location. Disabling or removing the widget
through Omarchy does not remove capture automatically.

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
an atomic replacement. Ancestor directories must be owned by root or the
current user and must not allow other users to replace their children.
Root-owned sticky directories such as `/tmp` are allowed as ancestors.
Nonblocking opens allow special files to be rejected without waiting for a
writer. Hard-linked lock files are refused before changing permissions.

The collector uses fixed CLI install locations rather than the inherited
executable search path. It removes loader and Python injection variables from
provider environments. Codex probes remove inherited OpenAI credential and
endpoint overrides and Codex access tokens. Both providers drop inherited
`OPENAI_*`, `CODEX_*`, `ANTHROPIC_*`, and `CLAUDE_*` variables before the selected
profile home is set. Provider commands start in `/`
to avoid loading configuration from the desktop process's working directory.
Claude probes also remove inherited Anthropic
credential, endpoint, and config-home overrides before setting the exact
profile location. App-server messages, command output, status-line input,
profile scans, cached data, and display strings are bounded. Requests and
refreshes have deadlines, and provider process groups are stopped on
completion, timeout, interruption, or widget destruction.

Before publishing a change, check the repository for `auth.json`, `.env`
files, access tokens, email addresses, absolute home paths, cache files, and
editor backups. The included `.gitignore` excludes the common local forms.
