# Changelog

## 2.1.1 — 2026-10-24

### Fixed
- Multi-disc releases could be split: each disc folder ('CD 1', 'Digital Media 02') was
  planned on its own, so a disc that also appeared on another release (the standard album,
  a box set) was removed and the rest of the set left behind. A disc is now only removed
  if the whole release is, or if the copy kept is in the same release. Discs kept this way
  are listed under "Kept intact".
- More disc folder names are recognised, including Lidarr's medium names ('12" Vinyl 01',
  'SHM-CD 01', 'Enhanced CD 01', 'Cassette 01') and 'Disc One' or 'CD II'.
- Comparing tracks in the dashboard during a rescan could fail with "database is locked":
  opening the fingerprint cache no longer writes to it.

## 2.1.0 — 2026-10-24

### Added
- Rescan from the dashboard (`serve --library FOLDER`), with live progress, speed, time left
  and a Stop button. Stopping loses nothing; decisions carry over to the new plan.
  `--scan-on-start` starts a scan when the server starts, and a first run with no plan
  yet shows the scan and opens the plan when it's done.
- Library page: tracks, size, playing time, artists, formats, bit depths, sample rates,
  the biggest artists and albums, and a scan history.
- New music: what was added or changed since the last completed scan, on the Overview
  and the Library page.
- Damaged files: when `fpcalc` can't read a file, it's decoded through `ffmpeg`, skipping
  bad frames, and matched anyway. Files where ffmpeg hit bad data are marked damaged (⚠);
  where there's another copy, the clean one is kept. Files that failed in an earlier
  version are retried once.
- `apply --act-on SCANNED=LIVE` (and `serve --act-on`): carry out a plan made from one
  mount, such as a read-only one, on another mount of the same files. Every file is
  re-checked there first. The quarantine folder may be a hidden folder inside the library.
- The dashboard works on phones: stacked track lists and a sticky Accept/Keep bar.
- `tools/make_demo_library.py` builds a fictional demo library for trying the tool out.

### Changed
- Comparing is about 25 times faster on large libraries (precomputed fingerprint
  probes, compared in parallel).
- The reclaimable meter on the Overview shows the total before any decisions are made.

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
- `musicdedup serve`: a browser dashboard to review a plan, compare and listen to copies
  side by side (A/B with waveforms and the difference highlighted), decide one by one or
  in bulk, then apply and undo. Login through Authelia, or LAN-only without one.
- No config file is needed any more. The cache has moved out of the script folder to
  `~/.cache/musicdedup/`.
