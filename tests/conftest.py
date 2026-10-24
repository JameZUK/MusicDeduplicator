"""Shared helpers: synthetic fingerprints and a fake library on a real filesystem.

The fake library writes real files (so the scanner, cache and executor run for
real) but replaces fpcalc and mutagen with lookups into a registry, so most tests
need neither tool installed.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from musicdedup.audio import AudioInfo
from musicdedup.cache import Cache
from musicdedup.fingerprint import ITEM_SECONDS, FingerprintError
from musicdedup.matcher import find_matches
from musicdedup.planner import Options, build_plan
from musicdedup.scanner import scan

FLAC16 = AudioInfo(lossless=True, bits=16, sample_rate=44100, channels=2)
FLAC24 = AudioInfo(lossless=True, bits=24, sample_rate=96000, channels=2)
MP3_320 = AudioInfo(lossless=False, bitrate=320000, sample_rate=44100, channels=2)


def make_fp(seed: int, n: int = 1500) -> np.ndarray:
    """A random fingerprint: different seeds behave like different songs."""
    return np.random.default_rng(seed).integers(0, 2**32, n, dtype=np.uint64).astype(np.uint32)


def noisy(fp: np.ndarray, ber: float, seed: int = 99) -> np.ndarray:
    """Flips each bit with probability `ber`, like a re-encode does."""
    rng = np.random.default_rng(seed)
    flips = np.zeros(len(fp), dtype=np.uint32)
    for bit in range(32):
        flips |= (rng.random(len(fp)) < ber).astype(np.uint32) << np.uint32(bit)
    return fp ^ flips


def edited(fp: np.ndarray, start: int, length: int, seed: int = 7) -> np.ndarray:
    """Replaces a stretch with unrelated audio, like a censored word."""
    out = fp.copy()
    out[start:start + length] = make_fp(seed, length)
    return out


class FakeLibrary:
    def __init__(self, root: str):
        self.root = root
        self.registry: dict[str, tuple] = {}
        self.fingerprint_calls = 0
        self._n = 0

    def path(self, rel: str) -> str:
        return os.path.join(self.root, rel)

    def add(self, rel: str, fp: np.ndarray | None, info: AudioInfo = FLAC16, *,
            album: str = '', track: int = 0, error: str | None = None, size: int | None = None) -> str:
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        self._n += 1
        with open(p, 'wb') as f:
            f.write(f'{self._n}:{rel}'.encode().ljust(size or 1000 + self._n, b'x'))
        info = AudioInfo(**{**info.to_dict(), 'album': album, 'track': track})
        self.registry[os.path.realpath(p)] = (fp, info, error)
        return p

    def extra(self, rel: str, data: bytes = b'cover') -> str:
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
        return p

    def album(self, folder: str, seeds: list[int], info: AudioInfo = FLAC16, *, album: str = '',
              transform=None, ext: str = 'flac') -> list[str]:
        """Adds one track per seed, named '01.flac' etc. `transform(fp)` alters each."""
        paths = []
        for i, s in enumerate(seeds, 1):
            fp = make_fp(s)
            if transform:
                fp = transform(fp)
            paths.append(self.add(f'{folder}/{i:02d}.{ext}', fp, info, album=album, track=i))
        return paths

    def fingerprint(self, path: str):
        self.fingerprint_calls += 1
        fp, _, error = self.registry[os.path.realpath(path)]
        if error:
            raise FingerprintError(error)
        return len(fp) * ITEM_SECONDS, fp

    def info(self, path: str) -> AudioInfo:
        return self.registry[os.path.realpath(path)][1]

    def scan(self, *, cache: Cache | None = None, roots: list[str] | None = None, **options):
        cache = cache or Cache(None)
        result = scan(roots or [self.root], cache, workers=2,
                      fingerprint_fn=self.fingerprint, info_fn=self.info)
        matches = find_matches(result.tracks)
        return result, matches, build_plan(result, matches, Options(**options))


@pytest.fixture(autouse=True)
def isolated_user_dirs(tmp_path, monkeypatch):
    """Keep tests away from the real cache, state and history."""
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'xdg-cache'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg-state'))


@pytest.fixture
def lib(tmp_path) -> FakeLibrary:
    root = tmp_path / 'music'
    root.mkdir()
    return FakeLibrary(str(root))


def rel(plan: dict, path: str) -> str:
    return os.path.relpath(path, plan['roots'][0])


def removed_folders(plan: dict) -> set[str]:
    return {rel(plan, r['folder']) for g in plan['groups'] for r in g['remove']}


def kept_folders(plan: dict) -> set[str]:
    return {rel(plan, g['keep']) for g in plan['groups']}
