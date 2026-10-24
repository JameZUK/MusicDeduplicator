# MusicDeduplicator

Find duplicate albums and tracks in a music library by **listening to them**, not
by trusting file names or tags, then remove the duplicates safely.

- **Compares the audio itself.** Every file is fingerprinted with Chromaprint and
  compared locally, so a FLAC and an MP3 of the same album match, and so do
  copies with different or missing tags. No account, API key or internet access
  is needed.
- **Keeps the best copy.** Lossless beats lossy, hi-res beats CD quality, higher
  bitrate beats lower. A copy is only removed if one of equal or better quality is kept.
- **Keeps releases intact.** Tracks are never taken out of an album you keep. A
  standard album isn't removed just because the deluxe edition contains it, a track
  an album repeats on purpose stays, and explicit and clean versions are never
  treated as duplicates. The tool finds exactly where they differ.
- **Never acts without a plan you can review.** `scan` changes nothing. It writes a
  plan saying what it would remove and which copy it keeps instead. `apply` re-checks
  every file before touching it, moves rather than deletes by default, and records
  everything so you can undo it.
- **Copes with messy libraries.** Corrupt files, symlinks, hard links, macOS `._`
  files and NAS metadata folders are handled. A folder holding anything unreadable
  is never removed.

## Install

You need Python 3.10 or newer and `fpcalc` from Chromaprint.

```bash
# 1. fpcalc
sudo apt install libchromaprint-tools     # Debian/Ubuntu
sudo dnf install chromaprint-tools        # Fedora
sudo pacman -S chromaprint                # Arch
brew install chromaprint                  # macOS
# Windows: download fpcalc from https://acoustid.org/chromaprint and put it on your PATH

# 2. musicdedup (pipx keeps it in its own environment)
pipx install git+https://github.com/JameZUK/MusicDeduplicator.git
```

If you don't have `pipx`, use a virtual environment. Recent Debian and Ubuntu
releases refuse a plain `pip install` with an "externally-managed-environment" error.

```bash
git clone https://github.com/JameZUK/MusicDeduplicator.git
cd MusicDeduplicator
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install .
```

## Use it in three steps

**1. Scan.** This only reads your files.

```bash
musicdedup scan ~/Music
```

The first scan fingerprints every file, at roughly 0.1 s per track with all CPU
cores busy. Results are cached, so later scans take seconds. It prints a report and
writes `musicdedup-plan.json`:

```
Duplicate folders: 3 folder(s) duplicate or are contained in another.
  [1] keep    Artist/Album [24-bit]  (11 tracks)
      remove  Artist/Album (CD rip)  (same album, 336.8 MB)
      remove  Downloads/Album  (same album, 298.1 MB)
  ...
Kept intact: smaller editions whose tracks are all in a bigger edition ...
Edited versions (same recording, different somewhere, e.g. explicit/clean): 2 ...
Audio files that could not be read (possibly corrupt): 4 ...

Plan: remove 25 files (22 audio), freeing 635.0 MB.
```

**2. Check the plan.** Use the report above, or open `musicdedup-plan.json`. Every
file to be removed lists the copy kept instead, and why.

**3. Apply it.** Move the duplicates out of your library (recommended), or delete them.

```bash
musicdedup apply musicdedup-plan.json --move-to ~/Duplicates --dry-run   # preview
musicdedup apply musicdedup-plan.json --move-to ~/Duplicates             # do it
musicdedup undo ~/Duplicates/musicdedup-journal-20261024-084704.jsonl    # changed your mind
```

`--delete` removes files permanently instead, and asks you to type `delete` to
confirm. Before acting on each file, `apply` checks that the file and the copy being
kept both still exist and haven't changed since the scan. Anything that fails a
check is skipped and listed.

## What counts as a duplicate

| Situation | What happens |
|---|---|
| Two folders with the same audio (any formats, any tags) | The best-quality folder is kept; the others are removed |
| A folder whose tracks are all in a bigger folder of the **same** edition (an incomplete copy) | Removed |
| A standard album whose tracks are all on the deluxe edition | **Kept** and reported. Add `--remove-smaller-editions` to remove it |
| The better copy is the smaller folder (e.g. FLAC album vs MP3 deluxe) | Both kept; nothing of better quality is ever removed |
| Explicit vs clean, radio edit, any version edited somewhere | Not a duplicate. Reported with the time where they differ |
| Different mix or remaster with different timing | Not a duplicate |
| Some tracks shared (compilations, best-ofs, partial overlap) | Both kept. Reported as shared tracks |
| The same track twice in one folder by accident (FLAC + MP3, `Song (1).flac`, same track number) | Reported. Add `--within-folders` to remove the extra copy |
| An album that repeats a track on purpose (different track numbers) | Kept intact |
| A folder containing an unreadable or corrupt audio file | Never removed. Corrupt files are listed |
| Silence, very short tracks | Never used as evidence of a duplicate on their own |
| Symlinks, hard links | Ignored (they aren't extra copies) |

When several copies are equally good, the tool keeps the copy with more tracks,
then better quality, then the one under a `--prefer` folder, then the
shallowest path, then the first alphabetically. The same library always produces
the same plan.

Only files directly inside a removed folder are removed: its audio plus its
artwork, `.nfo`, `.cue` and similar files. Subfolders are separate folders with
their own decision. Artwork is only removed once every audio file in the folder
has actually gone.

## Options

```
musicdedup scan LIBRARY [LIBRARY ...]
  -o, --plan FILE              where to write the plan (default: musicdedup-plan.json)
  --prefer FOLDER              keep copies under this folder when copies are equally good (repeatable)
  --remove-smaller-editions    also remove an edition whose tracks are all in a bigger one
  --within-folders             also remove accidental duplicate copies inside a folder
  --exclude PATTERN            skip folders matching a name or relative path pattern (repeatable)
  --workers N                  parallel fingerprinting jobs (default: number of CPUs)
  --cache FILE / --no-cache    fingerprint cache (default: ~/.cache/musicdedup/fingerprints.db)
  --full-report                print every entry instead of the first 25

musicdedup apply PLAN (--move-to DIR | --delete) [--dry-run] [--yes] [--journal FILE]
musicdedup undo JOURNAL [--dry-run]
musicdedup cache info|clear

All commands: -v/--verbose, -q/--quiet, --log-file FILE
```

Scanning several folders at once (for example `musicdedup scan ~/Music ~/Downloads
--prefer ~/Music`) finds duplicates across them. In quarantine, each scanned folder
gets its own subfolder.

Scheduled and unattended runs work: `scan` never prompts, and `apply` refuses to
proceed without `--yes` when it isn't run from a terminal.

## How it works

1. **Scan.** Walks the folders without following symlinks and fingerprints each audio
   file with `fpcalc` (the whole track, in parallel). Fingerprints, format and tags are
   cached, keyed by path, size and modification time to the nanosecond.
2. **Compare.** Tracks of similar length are compared by aligning their fingerprints
   and measuring the fraction of differing bits, overall and in 2.5-second windows.
   - Re-encodes of the same audio differ by under 10% overall, with no window above 13%.
   - An edited version differs little overall but has a window with a big difference,
     which pinpoints the edit.
   - Different mixes and different songs differ by 25% or more.

   These thresholds were measured on real libraries.
3. **Plan.** Folders are ranked, and each one is removed only if a higher-ranked kept
   folder holds an equal-or-better copy of every track in it. The plan is a JSON file;
   see `src/musicdedup/planner.py` for its layout.
4. **Apply.** Every file is re-checked against the plan before it's touched. Moves never
   overwrite, and every action is written to a journal immediately.

## Upgrading from 1.x (`musicorganise.py`)

Version 2 is a rewrite. AcoustID is no longer used: version 1 trusted AcoustID's
recording IDs, which treat explicit and clean versions as the same recording and
can give identical files different IDs. Version 2 compares the audio directly and
needs no API key. Your old `config.json` and `file_cache.db` are no longer used and
can be deleted.

`python3 musicorganise.py -p PATH -a list|move|delete [-m DIR] [--dry-run] [-y]` still
works as a wrapper around the new commands, but `musicdedup` is recommended.

## Development

```bash
pip install -e '.[dev]'
ruff check .
pytest                 # integration tests run when ffmpeg and fpcalc are installed
```

## License

MIT. See [LICENSE](LICENSE).
