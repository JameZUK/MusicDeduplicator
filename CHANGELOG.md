# Changelog

## 2.0.0 — 2026-10-24

A rewrite focused on safety and reliability.

### Fixed
- Every folder failed with "int() argument must be … not 'NoneType'" on the first run,
  so nothing was ever processed (#2).
- Folders of untagged or unreadable files were treated as duplicates of each other,
  and `delete` could remove distinct music.
- Symlinked folders matched the real album; deleting could remove the real files and
  leave dangling links.
- `move` and `delete` removed every file in a folder, including audio formats that
  were never compared and subfolders (`rmtree`).
- Moves could silently overwrite files with the same name.
- Within-folder dedup deleted distinct tracks that shared an AcoustID (silence,
  reprises), and the dry run could name the wrong file.
- Which copy was kept depended on process timing; dry runs could disagree with real runs.
- An AcoustID outage or a bad key silently fell back to tag matching, and the tool still deleted.
- Failed lookups were cached as "no match" permanently.
- Worker processes lost their configuration and logging on macOS, Windows and Python 3.14+.

### Changed
- Duplicates are found by comparing Chromaprint fingerprints locally, instead of by
  AcoustID lookups. No API key or network access is needed, and edited versions
  (explicit/clean) are told apart.
- Release awareness: albums are never stripped. Standard editions contained in a
  deluxe edition are kept unless `--remove-smaller-editions` is given, and tracks a
  release repeats on purpose are kept.
- New workflow: `scan` writes a reviewable plan, `apply` re-checks and carries it
  out, and `undo` reverses moves using a journal.
- Moving to a quarantine folder is the recommended default; deleting needs explicit confirmation.
- Packaged as `musicdedup` with a console command, a test suite and CI.
  `musicorganise.py` remains as a compatibility wrapper.
- No config file is needed any more. The cache has moved out of the script folder to
  `~/.cache/musicdedup/`.
