"""Waveform peaks for display, decoded with ffmpeg.

Peaks are on an absolute scale (0-255 of full scale) at a fixed number of buckets
per second, so two tracks can be drawn on one timeline and a quieter master looks
quieter. Adapted from Lyrion Anywhere's waveform analysis, by the same author.
"""

from __future__ import annotations

import functools
import shutil
import subprocess

import numpy as np

BUCKETS_PER_SECOND = 20
SAMPLE_RATE = 8000


class WaveformError(Exception):
    pass


def available() -> bool:
    return shutil.which('ffmpeg') is not None


@functools.lru_cache(maxsize=256)
def _peaks(path: str, size: int, mtime_ns: int) -> tuple[float, bytes]:
    # size and mtime_ns are part of the cache key, so a changed file is re-read.
    try:
        r = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', path, '-vn', '-ac', '1',
                            '-ar', str(SAMPLE_RATE), '-f', 's16le', '-'],
                           capture_output=True, timeout=120)
    except FileNotFoundError as e:
        raise WaveformError("ffmpeg is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise WaveformError("decoding took too long") from e
    if r.returncode != 0 or not r.stdout:
        msg = r.stderr.decode(errors='replace').strip().splitlines()
        raise WaveformError(msg[-1] if msg else "could not decode audio")
    samples = np.abs(np.frombuffer(r.stdout[:len(r.stdout) // 2 * 2], dtype='<i2').astype(np.int32))
    per = SAMPLE_RATE // BUCKETS_PER_SECOND
    n = max(1, -(-len(samples) // per))
    padded = np.zeros(n * per, dtype=np.int32)
    padded[:len(samples)] = samples
    peaks = np.minimum(255, padded.reshape(n, per).max(axis=1) * 255 // 32767).astype(np.uint8)
    return len(samples) / SAMPLE_RATE, peaks.tobytes()


def waveform(path: str, size: int, mtime_ns: int) -> dict:
    duration, peaks = _peaks(path, size, mtime_ns)
    return {'duration': round(duration, 3), 'per_second': BUCKETS_PER_SECOND, 'peak': list(peaks)}
