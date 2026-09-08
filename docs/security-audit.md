# Release security audit

Reviewed on 2026-09-08, starting from `e2538db` and including the local fixes
described below. Scope covers the Python runtime, QML panel, manifests,
documentation, tracked assets, and GitHub workflows. No live account probes
were run and no installed profile settings were changed by the audit.

## Release assessment

The confirmed findings below are fixed in the working tree. Claude setup now
requires an explicit action. Codex scheduled refresh remains enabled by
default and does not install hooks or edit Codex settings.

The [original marketplace report](https://github.com/omacom/omarchy-plugin-marketplace/issues/4731#issuecomment-5535234138)
identified unsafe cache paths, executable lookup through PATH, unbounded
transport, and incomplete process supervision. Version 1.0.1 addressed most
of those issues. This audit found remaining path and blocking-input gaps.

This is a source review with local regression tests, not a guarantee of
marketplace approval. The marketplace's [security baseline](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SECURITY.md)
checks a limited set of static patterns and binds its result to an exact
commit. The new release still needs its own marketplace verification.

## Findings and fixes

| Severity | Finding | Fix |
| --- | --- | --- |
| Medium | A permission-checked file could sit beneath an ancestor writable by another user, allowing path replacement. | Validate every directory component's owner and write permissions. Allow root-owned sticky ancestors, which protect owned children. |
| Medium | Refresh silently added a persistent command to Claude settings, including newly discovered profiles. This conflicts with the submission checklist's explicit configuration-consent requirement. | Require the Enable Claude capture button or `--setup-claude-capture`. Refresh never writes Claude settings. Preserve existing custom status lines and reject changes detected during setup. |
| Medium | Codex inherited account and endpoint overrides. Both providers inherited the desktop working directory, and loader filtering omitted `LD_AUDIT`. | Drop provider override variables and `LD_AUDIT`, set only the selected provider home, and start commands in `/`. |
| Low | Opening FIFO markers or settings could block before checking file type. The bridge also waited indefinitely for stdin EOF. | Discover credentials with metadata and validate through metadata-only handles. Use nonblocking file opens and a bounded, deadline-controlled bridge input reader. |
| Low | A hard-linked refresh lock could change an unrelated file's permissions. | Reject multiple links before chmod. |
| Low | CI used mutable checkout tags and persisted its Git credentials. | Pin checkout to a full commit and disable credential persistence. |
| Functional | Release archives omitted `claude_statusline.py`; system-owned CLI directories were rejected. | Package and compile the bridge, and accept protected root-owned CLI directories. |

## Verified protections

- Provider commands use fixed argument lists. Profile paths do not pass through
  a shell. The Claude status-line command quotes the plugin script path.
- Credential validation cannot read credential contents. Installed provider
  CLIs handle authentication. The collector does not make model requests.
- Private cache permissions, exclusive temporary files, atomic replacement,
  no-follow opens, payload limits, RPC deadlines, and process-group cleanup
  remain in place.
- Privacy mode omits identity fields from new cache data and cached output.
  Claude auth status still returns identity to the collector process; those
  fields are discarded unless identity display is enabled.
- Dynamic QML display text uses plain-text rendering.
- A pattern scan of tracked text found no token or private-key signatures or
  absolute personal home paths. Email matches were test fixtures. Visual
  inspection of the four tracked PNGs found no visible credentials or email
  addresses. This was not a full Git-history secret scan.

The provider methods match the documented
[Codex app-server rate-limit interface](https://learn.chatgpt.com/docs/app-server)
and [Claude status-line usage fields](https://code.claude.com/docs/en/statusline).

## Validation

- Python compilation and all 59 unit tests passed.
- QML syntax parsing with `qmlformat` and `omarchy plugin validate .`.
- Isolated CLI setup checks for successful installation, repeat setup, and
  refusal to replace a custom status line.
- Local execution of the release packaging step, with both archives checked
  for every runtime entry point.

The live popup and real provider authentication were not exercised. CI itself
and the marketplace's exact-commit scanner were not run by this audit.

## Remaining trust boundaries

Omarchy plugins and installed provider CLIs run as the desktop user. Permission
checks do not establish binary provenance or protect against an already
compromised user account. Profile configuration, CLI dependencies, system
executables, and administrator-managed proxy and certificate settings remain
trusted. This plugin does not sandbox provider processes or restrict their
network destinations.

Claude capture remains installed after the widget is disabled. Use **Remove
Claude Code usage capture** before uninstalling the plugin. This action was added
after the audit and removes only the matching command at the selected location. Existing installations from
the automatic-setup development version retain their hook. Setup checks for
concurrent edits before replacement, but another application does not share
the collector's lock; do not edit Claude settings during setup.

Turning privacy mode on redacts display output immediately, but an older
identity-bearing cache can remain on disk until a successful private refresh.
The cache is owner-only. Profile names and paths are not anonymized.
