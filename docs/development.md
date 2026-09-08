# Development and releases

## Local checks

Run these checks before committing:

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

If the widget still behaves like the previous version, run `omarchy restart
shell`. Plugin rescans can reuse cached QML on builds without
`Qt.clearComponentCache`; restarting the shell loads the updated code.

## Manual release checks

Use a separate test installation or back up existing settings before resetting
it. Check the installed plugin after a shell restart so cached QML does not
hide the current changes.

- Open settings, choose a folder, and save. Repeat by cancelling the picker;
  other unsaved settings should remain intact in both cases.
- Check default and custom names in the summary and account tabs. Clear a
  custom name to restore its default.
- Save the Claude location, enable capture, and send a Claude Code message.
  Refresh the widget and check the usage snapshot.
- Remove capture and verify that only AI Usage's status-line command disappears
  from the test profile. Repeat removal and check a profile with a custom
  status line to confirm it stays unchanged.
- Check both Claude account modes, OpenAI refresh modes, sleep, and privacy.

The [user guide](user-guide.md) documents the expected user-facing behavior.

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
