"""SQLite cache of fingerprints and audio info, keyed by path and validated by
size and nanosecond mtime. The cache is disposable: deleting it only costs time."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass

import numpy as np

from .audio import AudioInfo

SCHEMA_VERSION = 3


def default_cache_path() -> str:
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'musicdedup', 'fingerprints.db')


@dataclass
class CachedTrack:
    duration: float
    fingerprint: np.ndarray | None
    info: AudioInfo | None
    error: str | None


class Cache:
    def __init__(self, path: str | None):
        """path=None gives an in-memory cache (nothing persisted)."""
        self.path = path
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path or ':memory:', timeout=30)
        if path:
            self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        if version != SCHEMA_VERSION:
            # Older or unknown layout: start again rather than migrate a cache.
            self.conn.execute('DROP TABLE IF EXISTS tracks')
            self.conn.execute('DROP TABLE IF EXISTS file_cache')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS tracks (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                duration REAL,
                fingerprint BLOB,
                info TEXT,
                error TEXT,
                scanned_at REAL NOT NULL
            )''')
        self.conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        self.conn.commit()
        self._pending = 0

    def get(self, path: str, size: int, mtime_ns: int) -> CachedTrack | None:
        row = self.conn.execute(
            'SELECT size, mtime_ns, duration, fingerprint, info, error FROM tracks WHERE path = ?',
            (path,)).fetchone()
        if not row or row[0] != size or row[1] != mtime_ns:
            return None
        _, _, duration, blob, info, error = row
        fp = np.frombuffer(blob, dtype='<u4').astype(np.uint32) if blob is not None else None
        try:
            audio_info = AudioInfo.from_dict(json.loads(info)) if info else None
        except (ValueError, TypeError):
            return None
        return CachedTrack(duration=duration or 0.0, fingerprint=fp, info=audio_info, error=error)

    def put(self, path: str, size: int, mtime_ns: int, duration: float,
            fingerprint: np.ndarray | None, info: AudioInfo | None, error: str | None) -> None:
        blob = fingerprint.astype('<u4').tobytes() if fingerprint is not None else None
        self.conn.execute(
            'REPLACE INTO tracks (path, size, mtime_ns, duration, fingerprint, info, error, scanned_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (path, size, mtime_ns, duration, blob,
             json.dumps(info.to_dict()) if info else None, error, time.time()))
        self._pending += 1
        if self._pending >= 200:
            self.commit()

    def commit(self) -> None:
        self.conn.commit()
        self._pending = 0

    def prune(self, under: str, seen: set[str]) -> int:
        """Removes entries below directory `under` that weren't seen in this scan."""
        prefix = under.rstrip(os.sep) + os.sep
        rows = self.conn.execute(
            'SELECT path FROM tracks WHERE substr(path, 1, ?) = ?', (len(prefix), prefix)).fetchall()
        stale = [(p,) for (p,) in rows if p not in seen]
        self.conn.executemany('DELETE FROM tracks WHERE path = ?', stale)
        self.commit()
        return len(stale)

    def stats(self) -> dict:
        total, errors = self.conn.execute(
            'SELECT COUNT(*), COUNT(error) FROM tracks').fetchone()
        size = os.path.getsize(self.path) if self.path and os.path.exists(self.path) else 0
        return {'path': self.path, 'entries': total, 'errors': errors, 'bytes': size}

    def clear(self) -> None:
        self.conn.execute('DELETE FROM tracks')
        self.commit()
        self.conn.execute('VACUUM')

    def close(self) -> None:
        self.commit()
        self.conn.close()
