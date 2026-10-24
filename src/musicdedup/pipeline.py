"""A whole scan: walk and fingerprint, compare, plan, write the plan, record it.
Shared by `musicdedup scan` and the dashboard's Rescan button."""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from .cache import Cache
from .matcher import find_matches
from .planner import Options, build_plan
from .scanner import ProgressFn, scan
from .state import read_scans, record_scan

log = logging.getLogger(__name__)


def run_scan(roots: list[str], *, plan_path: str, cache_path: str | None, options: Options,
             excludes: list[str] | None = None, workers: int | None = None, progress: bool = False,
             on_progress: ProgressFn | None = None, cancel: threading.Event | None = None,
             state_dir: str | None = None) -> dict:
    started = time.time()
    real_roots = [os.path.realpath(r) for r in roots]
    previous = [s for s in (read_scans(state_dir) if state_dir else []) if s.get('roots') == real_roots]
    last = previous[-1].get('at') if previous else None
    cache = Cache(cache_path)
    try:
        result = scan(roots, cache, workers=workers, excludes=excludes, progress=progress,
                      on_progress=on_progress, cancel=cancel, new_since=last)
    finally:
        cache.close()
    # Everything this scan fingerprinted is in the cache by now; the next scan treats
    # files fingerprinted after this moment as new.
    fingerprinted_until = time.time()
    if state_dir:
        # "First scan" means no scan of these folders has completed yet, even if a
        # stopped one already fingerprinted some of them.
        result.stats['first scan'] = int(not previous)
    matches = find_matches(result.tracks, progress=progress, on_progress=on_progress, cancel=cancel)
    plan = build_plan(result, matches, options)
    plan['scan_seconds'] = round(time.time() - started)

    # Written atomically: a dashboard watching this file never sees half a plan.
    plan_path = os.path.abspath(plan_path)
    tmp = plan_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=1)
    os.replace(tmp, plan_path)

    if state_dir:
        s = plan['summary']
        record_scan(state_dir, {
            'at': fingerprinted_until, 'roots': plan['roots'], 'plan': plan_path, 'seconds': plan['scan_seconds'],
            'tracks': s['audio_files'], 'bytes': s['audio_bytes'],
            'new': plan['new_music']['new_tracks'], 'changed': plan['new_music']['changed_tracks'],
            'first_scan': plan['new_music']['first_scan'],
            'duplicate_folders': s['duplicate_folders'], 'bytes_to_free': s['bytes_to_free'],
            'unreadable': s['unreadable_audio_files'],
        })
    return plan
