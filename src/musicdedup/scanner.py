"""Walks music folders and fingerprints every audio file (using the cache)."""

from __future__ import annotations

import fnmatch
import logging
import os
import stat
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import numpy as np

from .audio import AudioInfo, is_audio, read_audio_info
from .cache import Cache
from .fingerprint import FingerprintError, FingerprintTimeout, is_low_information, run_fpcalc

log = logging.getLogger(__name__)

PROGRESS_LOG_SECONDS = 60

# Folders that are never music: NAS metadata, recycle bins, hidden folders.
SKIP_DIR_NAMES = frozenset({'@eaDir', '#recycle', '#snapshot', '$RECYCLE.BIN',
                            'System Volume Information', 'lost+found'})


@dataclass(eq=False)
class Track:
    path: str
    root: str
    size: int
    mtime_ns: int
    duration: float = 0.0
    fingerprint: np.ndarray | None = None
    info: AudioInfo | None = None
    error: str | None = None
    hardlink_of: str | None = None
    status: str = 'cached'      # cached | new | changed (since the previous scan)

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)

    @property
    def usable(self) -> bool:
        return self.error is None and self.hardlink_of is None and self.fingerprint is not None

    @property
    def weak(self) -> bool:
        """Too short or uniform (silence, tones) to identify on its own."""
        return self.fingerprint is None or is_low_information(self.fingerprint)

    def quality(self) -> tuple:
        return (self.info or AudioInfo(lossless=False)).quality()


@dataclass(frozen=True)
class FileRef:
    """A file as it was when scanned, so it can be re-checked before acting."""
    path: str
    size: int
    mtime_ns: int


@dataclass
class Folder:
    path: str
    root: str
    tracks: list[Track] = field(default_factory=list)
    extras: list[FileRef] = field(default_factory=list)    # non-audio files
    problems: list[str] = field(default_factory=list)      # reasons it must not be removed


@dataclass
class ScanResult:
    roots: list[str]
    tracks: list[Track]
    folders: dict[str, Folder]
    skipped: Counter
    stats: Counter


class ScanCancelled(Exception):
    """The scan was stopped on request. Work done so far is cached."""


# progress(stage, done, total): stage is 'walking', 'fingerprinting' or 'comparing'.
ProgressFn = Callable[[str, int, int], None]

# fingerprint_fn(path) -> (duration, fingerprint); info_fn(path) -> AudioInfo.
FingerprintFn = Callable[[str], tuple[float, np.ndarray]]
InfoFn = Callable[[str], AudioInfo]


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def _skip_dir(name: str, rel: str, excludes: list[str]) -> bool:
    if name.startswith('.') or name in SKIP_DIR_NAMES:
        return True
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) for p in excludes)


def _walk(roots: list[str], excludes: list[str], exclude_paths: list[str],
          skipped: Counter, on_progress=None, cancel=None) -> tuple[dict[str, Folder], list[Track]]:
    folders: dict[str, Folder] = {}
    tracks: list[Track] = []
    seen_inodes: dict[tuple[int, int], str] = {}

    def onerror(e: OSError) -> None:
        log.warning("Cannot read %s: %s", e.filename, e.strerror)
        skipped['unreadable folders'] += 1

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, onerror=onerror, followlinks=False):
            keep = []
            for d in sorted(dirnames):
                full = os.path.join(dirpath, d)
                rel = os.path.relpath(full, root)
                if os.path.islink(full):
                    skipped['symlinked folders'] += 1
                elif any(full == p or full.startswith(p + os.sep) for p in exclude_paths):
                    skipped['excluded folders'] += 1
                elif _skip_dir(d, rel, excludes):
                    skipped['hidden or system folders'] += 1
                else:
                    keep.append(d)
            dirnames[:] = keep

            folder = Folder(path=dirpath, root=root)
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                try:
                    st = os.lstat(full)
                except OSError as e:
                    log.warning("Cannot stat %s: %s", full, e.strerror)
                    folder.problems.append(f"{name}: unreadable ({e.strerror})")
                    continue
                if stat.S_ISLNK(st.st_mode):
                    skipped['symlinked files'] += 1
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                if name.startswith('._') or not is_audio(name):
                    folder.extras.append(FileRef(full, st.st_size, st.st_mtime_ns))
                    continue
                track = Track(path=full, root=root, size=st.st_size, mtime_ns=st.st_mtime_ns)
                inode = (st.st_dev, st.st_ino)
                if inode in seen_inodes:
                    track.hardlink_of = seen_inodes[inode]
                    folder.problems.append(f"{name}: hard link to {seen_inodes[inode]}")
                    skipped['hard-linked files'] += 1
                else:
                    seen_inodes[inode] = full
                folder.tracks.append(track)
                tracks.append(track)
            if folder.tracks:
                folders[dirpath] = folder
                if on_progress and len(folders) % 50 == 0:
                    on_progress('walking', len(tracks), 0)
            if cancel is not None and cancel.is_set():
                raise ScanCancelled()
    return folders, tracks


def _analyse(path: str, fingerprint_fn: FingerprintFn, info_fn: InfoFn):
    info = info_fn(path)
    try:
        duration, fp = fingerprint_fn(path)
    except FingerprintTimeout as e:
        return info, 0.0, None, str(e), True
    except FingerprintError as e:
        return info, 0.0, None, str(e), False
    return info, duration, fp, None, False


def scan(roots: list[str], cache: Cache, *, workers: int | None = None,
         excludes: list[str] | None = None, exclude_paths: list[str] | None = None,
         fingerprint_fn: FingerprintFn = run_fpcalc, info_fn: InfoFn = read_audio_info,
         progress: bool = False, on_progress: ProgressFn | None = None,
         cancel: threading.Event | None = None, new_since: float | None = None) -> ScanResult:
    """Walks and fingerprints. `on_progress` is called as work proceeds; setting
    `cancel` stops the scan with ScanCancelled (finished work stays cached).
    `new_since` is when the previous *completed* scan ran: files first fingerprinted
    after it count as new even if a stopped scan did the work."""
    roots = [os.path.realpath(r) for r in roots]
    exclude_paths = [os.path.realpath(p) for p in exclude_paths or []]
    skipped: Counter = Counter()
    stats: Counter = Counter()
    stats['first scan'] = int(all(cache.count_under(r) == 0 for r in roots))
    folders, tracks = _walk(roots, excludes or [], exclude_paths, skipped, on_progress, cancel)
    log.info("Found %d audio files in %d folders", len(tracks), len(folders))

    todo = []
    for t in tracks:
        if t.hardlink_of:
            continue
        cached = cache.get(t.path, t.size, t.mtime_ns)
        if cached:
            t.duration, t.fingerprint, t.info, t.error = (
                cached.duration, cached.fingerprint, cached.info, cached.error)
            stats['from cache'] += 1
            if new_since is not None and cached.scanned_at > new_since:
                t.status = 'new'
                stats['new files'] += 1
        else:
            t.status = 'changed' if cache.known(t.path) else 'new'
            stats[f'{t.status} files'] += 1
            todo.append(t)

    if todo:
        log.info("Fingerprinting %d new or changed files (%d from cache)", len(todo), stats['from cache'])
        bar = None
        if progress:
            from tqdm import tqdm
            bar = tqdm(total=len(todo), unit='file', desc='Fingerprinting')
        pool = ThreadPoolExecutor(max_workers=workers or os.cpu_count() or 2)
        started = last_report = time.monotonic()
        try:
            futures = {pool.submit(_analyse, t.path, fingerprint_fn, info_fn): t for t in todo}
            for fut in as_completed(futures):
                t = futures[fut]
                t.info, t.duration, t.fingerprint, t.error, transient = fut.result()
                stats['fingerprinted'] += 1
                if not transient:
                    cache.put(t.path, t.size, t.mtime_ns, t.duration, t.fingerprint, t.info, t.error)
                if on_progress:
                    on_progress('fingerprinting', stats['fingerprinted'], len(todo))
                if cancel is not None and cancel.is_set():
                    raise ScanCancelled()
                if bar:
                    bar.update()
                elif time.monotonic() - last_report >= PROGRESS_LOG_SECONDS:
                    # No progress bar (e.g. not a terminal): log progress for unattended runs.
                    last_report = time.monotonic()
                    done = stats['fingerprinted']
                    rate = done / (last_report - started)
                    log.info("Fingerprinted %d of %d files (%.1f/s, about %s left)", done, len(todo), rate,
                             _duration((len(todo) - done) / rate if rate else 0))
        except (KeyboardInterrupt, ScanCancelled):
            pool.shutdown(wait=False, cancel_futures=True)
            cache.commit()
            raise
        finally:
            pool.shutdown(wait=True)
            if bar:
                bar.close()
            cache.commit()

    for t in tracks:
        if t.error:
            stats['unreadable audio files'] += 1
            log.warning("Cannot fingerprint %s: %s", t.path, t.error)
            folders[t.folder].problems.append(f"{os.path.basename(t.path)}: {t.error}")

    seen = {t.path for t in tracks}
    for root in roots:
        stats['stale cache entries pruned'] += cache.prune(root, seen)
    return ScanResult(roots=roots, tracks=tracks, folders=folders, skipped=skipped, stats=stats)
