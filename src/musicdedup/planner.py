"""Turns scan results and matches into a plan: which files to remove, and why.

Rules, in order of importance:
- A file is only planned for removal if another copy of the same audio, of equal
  or better quality, is kept. Every removal names that copy.
- A folder is removed as a whole only if every audio file in it is covered by one
  other kept folder, and nothing in it is unreadable or a hard link.
- Releases stay intact. Tracks are never removed from a kept folder, except for
  accidental copies inside one folder when asked (--within-folders); a track a
  release repeats on purpose is never one. A smaller folder contained in a bigger
  one is only removed if it's the same edition (an incomplete copy), unless asked
  (--remove-smaller-editions): a standard album is a distinct release from its deluxe.
- Edited versions (explicit vs clean etc.) are never duplicates.
- Ties are broken deterministically, so the same library always gives the same plan.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import __version__
from .editions import Release, accidental_copy, release_of, same_edition
from .matcher import Matches
from .scanner import Folder, ScanResult, Track

log = logging.getLogger(__name__)

PLAN_FORMAT = 'musicdedup-plan'
PLAN_VERSION = 1


@dataclass
class Options:
    prefer: list[str] = field(default_factory=list)
    within_folders: bool = False
    remove_smaller_editions: bool = False


def _ref(t: Track) -> dict:
    return {'path': t.path, 'size': t.size, 'mtime_ns': t.mtime_ns}


def _quality_score(t: Track) -> int:
    """Track.quality() as a number that can be summed over a folder."""
    lossless, clean, bits, rate, channels, bitrate = t.quality()
    if lossless:
        return 10**12 + clean * 10**11 + bits * 10**9 + rate * 10 + channels
    return clean * 10**8 + channels * 10**7 + bitrate


def _format_time(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


class _Planner:
    def __init__(self, scan: ScanResult, matches: Matches, options: Options):
        self.scan = scan
        self.m = matches
        self.prefer = [os.path.realpath(p) for p in options.prefer]
        self.within_enabled = options.within_folders
        self.remove_smaller_editions = options.remove_smaller_editions
        self.editions_kept: list[dict] = []
        self.repeated: list[dict] = []
        self._releases: dict[str, Release] = {}
        self.removed: set[Track] = set()
        self.removals: list[dict] = []
        self.groups: list[dict] = []
        self.within: list[dict] = []
        self.blocked: list[dict] = []
        # Within-folder duplicate -> the best copy in the same folder.
        self.dup_of: dict[Track, Track] = {}
        self.removal_of: dict[Track, dict] = {}

    # -- helpers ---------------------------------------------------------------

    def _preference(self, path: str) -> int:
        for i, p in enumerate(self.prefer):
            if path == p or path.startswith(p + os.sep):
                return len(self.prefer) - i
        return 0

    @staticmethod
    def _track_rank(t: Track) -> tuple:
        # Best first: highest quality, then shortest name (not "Song (1)"), then alphabetical.
        # Size is ignored: equal-quality copies differ only in tag bytes.
        return (tuple(-x for x in t.quality()), len(t.path), t.path)

    def _tracks(self, folder: Folder) -> list[Track]:
        return [t for t in folder.tracks if t not in self.removed]

    def _distinct(self, folder: Folder) -> list[Track]:
        """Usable tracks, counting each audio once: within-folder duplicates are left out."""
        return [t for t in self._tracks(folder) if t.usable and t not in self.dup_of]

    def _folder_rank(self, folder: Folder) -> tuple:
        """Order in which folders claim the right to be kept. A folder can only be
        removed in favour of one ranked earlier, so the order must put every folder
        that could cover another first: more tracks, then better quality. Only then
        the preferred location, the shallowest path, and alphabetical order.
        Not size: see _track_rank."""
        tracks = self._distinct(folder)
        quality = sum(_quality_score(t) for t in tracks)
        return (-len(tracks), -quality, -self._preference(folder.path),
                folder.path.count(os.sep), folder.path)

    def _release(self, folder: Folder) -> Release:
        if folder.path not in self._releases:
            albums = [t.info.album for t in folder.tracks if t.info]
            self._releases[folder.path] = release_of(folder.path, albums)
        return self._releases[folder.path]

    def _linked(self, t: Track):
        yield from self.m.same.get(t, ())
        yield from self.m.weak.get(t, ())

    # -- within-folder duplicates ---------------------------------------------

    def plan_within_folders(self) -> None:
        for folder in self.scan.folders.values():
            members = set(folder.tracks)
            done: set[Track] = set()
            for t in sorted(folder.tracks, key=self._track_rank):
                if t in done or not t.usable:
                    continue
                # Only direct same-audio matches with the best copy, never weak ones:
                # two silent or very short tracks in one folder are not duplicates.
                copies = [o for o in self.m.same.get(t, ()) if o in members and o not in done]
                if not copies:
                    continue
                done.add(t)
                for o in sorted(copies, key=self._track_rank):
                    done.add(o)
                    ti, oi = t.info, o.info
                    if not accidental_copy(os.path.basename(t.path), ti.track if ti else 0, ti.disc if ti else 0,
                                           os.path.basename(o.path), oi.track if oi else 0, oi.disc if oi else 0):
                        # Part of the release's track list (e.g. a reprise): keep intact.
                        self.repeated.append({'folder': folder.path, 'paths': [t.path, o.path]})
                        continue
                    self.dup_of[o] = t
                    entry = {'keep': _ref(t), 'remove': _ref(o), 'folder': folder.path}
                    self.within.append(entry)
                    if self.within_enabled:
                        self.removed.add(o)
                        self.removal_of[o] = {
                            **_ref(o), 'keep': _ref(t), 'reason': 'within-folder',
                            'detail': 'same audio as another file in this folder'}
                        self.removals.append(self.removal_of[o])

    # -- folder duplicates -------------------------------------------------------

    def _cover(self, keeper: Folder, folder: Folder) -> dict[Track, Track] | None:
        """Pairs every track of `folder` with a distinct track of `keeper` that has the
        same audio and equal or better quality. Returns None if that's impossible.
        Within-folder duplicates in `folder` pair with whatever their best copy pairs with."""
        keeper_tracks = set(self._distinct(keeper))
        options = {}
        for t in self._distinct(folder):
            cands = [o for o in self._linked(t)
                     if o in keeper_tracks and o.quality() >= t.quality()]
            if not cands:
                return None
            options[t] = sorted(cands, key=self._track_rank)
        # Small bipartite matching (augmenting paths); albums are tiny.
        owner: dict[Track, Track] = {}

        def assign(t: Track, seen: set[Track]) -> bool:
            for o in options[t]:
                if o in seen:
                    continue
                seen.add(o)
                if o not in owner or assign(owner[o], seen):
                    owner[o] = t
                    return True
            return False

        for t in sorted(options, key=lambda x: (len(options[x]), x.path)):
            if not assign(t, set()):
                return None
        pairs = {t: o for o, t in owner.items()}
        if not any(self.m.is_same(t, o) for t, o in pairs.items()):
            return None  # only silence/short tracks matched: not evidence of a duplicate
        for t in self._tracks(folder):
            if t in self.dup_of and self.dup_of[t] in pairs:
                pairs[t] = pairs[self.dup_of[t]]
        return pairs

    def plan_folders(self) -> None:
        folders = [f for f in self.scan.folders.values() if any(t.usable for t in f.tracks)]
        folders.sort(key=self._folder_rank)
        kept: set[str] = set()
        group_of: dict[str, dict] = {}
        for folder in folders:
            neighbours = {o.folder for t in self._tracks(folder) for o in self._linked(t)}
            covering, other_editions = [], []
            for keeper in (self.scan.folders[p] for p in neighbours if p in kept and p != folder.path):
                pairs = self._cover(keeper, folder)
                if pairs is None:
                    continue
                # Prefer the keeper whose copies are better than the ones removed.
                upgrades = sum(1 for t, o in pairs.items() if o.quality() > t.quality())
                entry = ((-upgrades, self._folder_rank(keeper)), keeper, pairs)
                contained = len(self._distinct(folder)) < len(self._distinct(keeper))
                if (contained and not self.remove_smaller_editions
                        and not same_edition(self._release(folder), self._release(keeper))):
                    other_editions.append(entry)
                else:
                    covering.append(entry)
            if not covering:
                if other_editions:
                    _, keeper, _ = min(other_editions, key=lambda c: c[0])
                    self.editions_kept.append({
                        'folder': folder.path, 'edition': self._release(folder).describe(),
                        'contained_in': keeper.path, 'contained_in_edition': self._release(keeper).describe(),
                        'tracks': len(self._distinct(folder))})
                kept.add(folder.path)
                continue
            _, keeper, pairs = min(covering, key=lambda c: c[0])
            if folder.problems:
                self.blocked.append({'folder': folder.path, 'copy_of': keeper.path,
                                     'problems': folder.problems})
                kept.add(folder.path)
                continue
            self._remove_folder(folder, keeper, pairs, group_of)

    def _remove_folder(self, folder: Folder, keeper: Folder, pairs: dict[Track, Track],
                       group_of: dict[str, dict]) -> None:
        distinct = len(self._distinct(folder))
        kind = 'duplicate' if distinct == len(self._distinct(keeper)) else 'contained'
        group = group_of.get(keeper.path)
        if group is None:
            group = {'id': len(self.groups) + 1, 'keep': keeper.path,
                     'keep_tracks': len(self._distinct(keeper)), 'remove': []}
            group_of[keeper.path] = group
            self.groups.append(group)
        group['remove'].append({'folder': folder.path, 'kind': kind, 'tracks': distinct,
                                'bytes': sum(t.size for t in pairs)})
        detail = ('identical album' if kind == 'duplicate'
                  else f'all {distinct} tracks are also in a larger kept folder')
        for t, o in sorted(pairs.items(), key=lambda p: p[0].path):
            self.removed.add(t)
            self.removals.append({**_ref(t), 'keep': _ref(o), 'reason': f'{kind}-album',
                                  'group': group['id'], 'detail': detail})
        # Copies already planned as within-folder duplicates named a file in this
        # folder as the one to keep; that file is going, so point them at its keeper.
        for t in folder.tracks:
            entry = self.removal_of.get(t)
            if entry is not None and self.dup_of.get(t) in pairs:
                entry.update(keep=_ref(pairs[self.dup_of[t]]), reason=f'{kind}-album',
                             group=group['id'], detail=detail)
        # The folder is emptied of audio, so its artwork etc. goes with it.
        for e in folder.extras:
            self.removals.append({'path': e.path, 'size': e.size, 'mtime_ns': e.mtime_ns,
                                  'keep': None, 'reason': 'extra', 'group': group['id'],
                                  'detail': 'non-audio file in a removed folder'})

    # -- reports -----------------------------------------------------------------

    def overlaps(self) -> list[dict]:
        """Tracks shared between folders that are both kept: compilations, deluxe
        editions, partial copies. Reported, never acted on."""
        shared: dict[tuple[str, str], int] = defaultdict(int)
        for t in self.scan.tracks:
            if t in self.removed or not t.usable:
                continue
            others = {o.folder for o in self.m.same.get(t, ()) if o not in self.removed}
            for f in others - {t.folder}:
                shared[(t.folder, f)] += 1
        out = []
        for (a, b), n in shared.items():
            if a < b:
                out.append({'folders': [a, b], 'shared_tracks': n,
                            'tracks': [len(self._tracks(self.scan.folders[a])),
                                       len(self._tracks(self.scan.folders[b]))]})
        out.sort(key=lambda x: (-x['shared_tracks'], x['folders']))
        return out

    def folder_details(self) -> dict[str, dict]:
        """Track lists and formats for every folder the plan mentions, so a viewer
        (e.g. the dashboard) can show the plan without rescanning."""
        paths: set[str] = set()
        for g in self.groups:
            paths.add(g['keep'])
            paths.update(r['folder'] for r in g['remove'])
        for e in self.editions_kept:
            paths.update((e['folder'], e['contained_in']))
        for b in self.blocked:
            paths.update((b['folder'], b['copy_of']))
        for w in self.within:
            paths.add(w['folder'])
        for a, b, _ in self.m.variants:
            paths.update((a.folder, b.folder))
        for x in self.overlaps():
            paths.update(x['folders'])
        out = {}
        for path in sorted(paths):
            folder = self.scan.folders.get(path)
            if folder is None:
                continue
            tracks = sorted(folder.tracks, key=lambda t: ((t.info.disc, t.info.track) if t.info else (0, 0), t.path))
            out[path] = {
                'release': self._release(folder).describe(),
                'tracks': [{
                    **_ref(t), 'duration': round(t.duration, 2), 'error': t.error,
                    'quality': t.info.describe() if t.info else 'unknown',
                    **({k: getattr(t.info, k) for k in ('lossless', 'bits', 'sample_rate', 'bitrate',
                                                        'artist', 'album', 'title', 'track', 'disc', 'damaged')}
                       if t.info else {}),
                } for t in tracks],
                'extras': [{'path': e.path, 'size': e.size, 'mtime_ns': e.mtime_ns} for e in folder.extras],
                'problems': folder.problems,
            }
        return out

    def variants(self) -> list[dict]:
        out = []
        for a, b, c in self.m.variants:
            out.append({'paths': sorted([a.path, b.path]), 'ber': round(c.ber, 3),
                        'max_window_ber': round(c.max_block_ber, 3),
                        'differs_at': _format_time(c.max_block_at)})
        out.sort(key=lambda x: x['paths'])
        return out


def _library_stats(scan: ScanResult) -> dict:
    """Whole-collection statistics for the dashboard."""
    artists: dict[str, dict] = {}
    bits: dict[str, int] = defaultdict(int)
    rates: dict[str, int] = defaultdict(int)
    bitrates: dict[str, int] = defaultdict(int)
    duration = 0.0
    for t in scan.tracks:
        duration += t.duration or 0
        info = t.info
        name = (info.artist.strip() if info and info.artist else '') or \
            os.path.relpath(t.folder, t.root).split(os.sep)[0]
        a = artists.setdefault(name.casefold(), {'artist': name, 'tracks': 0, 'bytes': 0})
        a['tracks'] += 1
        a['bytes'] += t.size
        if not info:
            continue
        if info.lossless:
            bits[f"{info.bits or 16}-bit"] += 1
            if info.sample_rate:
                rates[f"{info.sample_rate / 1000:g} kHz"] += 1
        elif info.bitrate:
            kbps = info.bitrate / 1000
            bucket = ('under 192 kbps' if kbps < 190 else '192-255 kbps' if kbps < 250
                      else '256-319 kbps' if kbps < 310 else '320 kbps and up')
            bitrates[bucket] += 1
    albums = sorted(({'folder': f.path, 'tracks': len(f.tracks), 'bytes': sum(t.size for t in f.tracks)}
                     for f in scan.folders.values()), key=lambda x: -x['bytes'])
    top = sorted(artists.values(), key=lambda x: -x['bytes'])
    return {
        'tracks': len(scan.tracks),
        'bytes': sum(t.size for t in scan.tracks),
        'duration_seconds': round(duration),
        'artists': len(artists),
        'albums': len(scan.folders),
        'bit_depth': dict(sorted(bits.items())),
        'sample_rate': dict(sorted(rates.items(), key=lambda kv: float(kv[0].split()[0]))),
        'lossy_bitrate': dict(bitrates),
        'top_artists': top[:15],
        'largest_albums': albums[:10],
    }


def _new_music(scan: ScanResult) -> dict:
    """Folders with files that are new or changed since the previous scan."""
    per: dict[str, dict] = {}
    for t in scan.tracks:
        if t.status == 'cached':
            continue
        e = per.setdefault(t.folder, {'folder': t.folder, 'new': 0, 'changed': 0,
                                      'tracks': len(scan.folders[t.folder].tracks) if t.folder in scan.folders else 0})
        e[t.status] += 1
    return {
        'first_scan': bool(scan.stats.get('first scan')),
        'new_tracks': sum(e['new'] for e in per.values()),
        'changed_tracks': sum(e['changed'] for e in per.values()),
        'folders': sorted(per.values(), key=lambda e: e['folder'])[:1000],
    }


def build_plan(scan: ScanResult, matches: Matches, options: Options | None = None) -> dict:
    options = options or Options()
    p = _Planner(scan, matches, options)
    p.plan_within_folders()
    p.plan_folders()
    removals = sorted(p.removals, key=lambda r: r['path'])
    # Defence in depth: never plan to remove a file another removal relies on.
    paths = {r['path'] for r in removals}
    bad = [r for r in removals if r['keep'] and r['keep']['path'] in paths]
    for r in bad:
        log.error("Internal error: not removing %s, its kept copy is also planned for removal", r['path'])
    removals = [r for r in removals if r not in bad]
    unreadable = sorted(({'path': t.path, 'error': t.error} for t in scan.tracks if t.error),
                        key=lambda x: x['path'])
    damaged = sorted(t.path for t in scan.tracks if t.info and t.info.damaged and not t.error)
    audio = [r for r in removals if r['reason'] != 'extra']
    quality: dict[str, int] = defaultdict(int)
    formats: dict[str, int] = defaultdict(int)
    for t in scan.tracks:
        formats[os.path.splitext(t.path)[1].lower().lstrip('.')] += 1
        if not t.info:
            quality['unknown'] += 1
        elif t.info.lossless:
            quality['hi-res' if (t.info.bits or 16) > 16 or t.info.sample_rate > 48000 else 'cd'] += 1
        else:
            quality['lossy'] += 1
    return {
        'format': PLAN_FORMAT,
        'version': PLAN_VERSION,
        'tool_version': __version__,
        'created': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'roots': scan.roots,
        'options': {'prefer': p.prefer, 'within_folders': options.within_folders,
                    'remove_smaller_editions': options.remove_smaller_editions},
        'summary': {
            'audio_files': len(scan.tracks),
            'audio_bytes': sum(t.size for t in scan.tracks),
            'folders': len(scan.folders),
            'quality': dict(sorted(quality.items())),
            'formats': dict(sorted(formats.items(), key=lambda kv: -kv[1])),
            'duplicate_folders': sum(len(g['remove']) for g in p.groups),
            'files_to_remove': len(removals),
            'audio_files_to_remove': len(audio),
            'bytes_to_free': sum(r['size'] for r in removals),
            'within_folder_duplicates': len(p.within),
            'smaller_editions_kept': len(p.editions_kept),
            'repeated_tracks_kept': len(p.repeated),
            'edited_versions': len(matches.variants),
            'unreadable_audio_files': len(unreadable),
            'damaged_audio_files': len(damaged),
            'blocked_folders': len(p.blocked),
            **{k: v for k, v in scan.skipped.items()},
            **{k: v for k, v in scan.stats.items()},
        },
        'groups': p.groups,
        'removals': removals,
        'within_folder': p.within,
        'smaller_editions_kept': p.editions_kept,
        'repeated_in_release': p.repeated,
        'blocked': p.blocked,
        'edited_versions': p.variants(),
        'shared_tracks': p.overlaps(),
        'unreadable': unreadable,
        'damaged': damaged,
        'folders': p.folder_details(),
        'library': _library_stats(scan),
        'new_music': _new_music(scan),
    }
