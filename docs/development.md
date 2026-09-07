# Development and releases

## Local checks

Run both checks before committing:

```bash
omarchy plugin validate .
/usr/bin/python3 -m py_compile collector.py claude_statusline.py folder_picker.py
/usr/bin/python3 -m unittest discover -s tests -v
```

The Omarchy validator checks the manifest, plugin ID, entry points, declared
kinds, and repository layout. Python compilation catches syntax errors in the
collector, Claude status-line bridge, and folder picker. The unit tests cover
path, permission, provider separation, process, transport, and payload
boundaries.

Saving a file through the installed plugin path reloads the plugin in the
running Omarchy shell. If it does not reload, run:

```bash
omarchy-shell shell rescanPlugins
```

## Releases

Releases use tags in the form `vMAJOR.MINOR.PATCH`. Before creating a tag:

1. Set the same version in `manifest.json`.
2. Add a matching `## VERSION - DATE` entry to `CHANGELOG.md`.
3. Run the local checks.
4. Push the commit, then push the tag.

The release workflow validates the tag, extracts its changelog entry, builds
`.tar.gz` and `.zip` archives, writes SHA-256 checksums, and creates the GitHub
release. The tagged commit must be on the repository's default branch because
that is the branch the marketplace follows.
