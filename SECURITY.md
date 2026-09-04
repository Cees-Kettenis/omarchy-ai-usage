# Security and privacy

AI Usage runs as the current desktop user. Omarchy plugins are not
sandboxed, so review the source before installing it.

The collector never parses or copies `auth.json`. It checks for the file and
starts the installed `codex app-server` with that folder as `CODEX_HOME`.

Privacy mode is enabled by default. In that mode, the collector does not call
the account identity endpoint and does not write email or subscription details
to its cache. Turning privacy mode off allows those fields to be requested and
cached.

Runtime data is written outside the plugin repository under
`$XDG_CACHE_HOME/omarchy/ai-usage/`, or `~/.cache/omarchy/ai-usage/`
when `XDG_CACHE_HOME` is unset. The cache directory uses mode `0700`, and the
status file uses mode `0600`.

Before publishing a change, check the repository for `auth.json`, `.env`
files, access tokens, email addresses, absolute home paths, cache files, and
editor backups. The included `.gitignore` excludes the common local forms.
