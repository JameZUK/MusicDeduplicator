"""Turning review decisions (from the dashboard) into a plan.

A decision per duplicate group is one of:
  'accept'          carry out the group as planned
  'skip'            leave every folder in the group alone
  {'keep': FOLDER}  keep a different folder of the group instead

Choosing a different keeper re-pairs tracks through the original keeper (same
audio is transitive across those strict matches). It is only allowed for folders
that hold the same album: a folder with tracks missing can't stand in for one
with more. Other folders that the new keeper can't fully cover are kept, and
choosing a lower-quality copy is allowed but reported, so the UI can confirm it.

Within-folder removals are included only if listed in 'within' (by path).
Undecided groups are left out: nothing is removed without a decision.
"""

from __future__ import annotations

import copy
import os


class DecisionError(Exception):
    pass


def _quality(track: dict) -> tuple:
    if track.get('lossless'):
        return (1, track.get('bits') or 16, track.get('sample_rate') or 0, 0)
    return (0, 0, 0, track.get('bitrate') or 0)


def _ref(track: dict) -> dict:
    return {'path': track['path'], 'size': track['size'], 'mtime_ns': track['mtime_ns']}


def _rekeep(plan: dict, group: dict, new_keep: str) -> tuple[list[dict], list[str]]:
    old_keep = group['keep']
    members = {r['folder']: r for r in group['remove']}
    if new_keep not in members:
        raise DecisionError(f"{new_keep} is not part of group {group['id']}")
    if members[new_keep]['kind'] != 'duplicate':
        raise DecisionError(f"{new_keep} is missing tracks, so it can't replace {old_keep}")
    folders = plan['folders']
    tracks = {t['path']: t for f in (old_keep, *members) for t in folders[f]['tracks']}
    gid = group['id']
    audio = [r for r in plan['removals'] if r.get('group') == gid and r['reason'] != 'extra']

    # removed track -> old keeper track, per folder
    to_old: dict[str, dict[str, str]] = {f: {} for f in members}
    for r in audio:
        folder = os.path.dirname(r['path'])
        if folder in to_old:
            to_old[folder][r['path']] = r['keep']['path']
    old_to_new: dict[str, str] = {}
    for new_path, old_path in sorted(to_old[new_keep].items()):
        old_to_new.setdefault(old_path, new_path)
    # Copies inside the old keeper follow their best copy there.
    for w in plan.get('within_folder', []):
        if w['folder'] == old_keep and w['keep']['path'] in old_to_new:
            old_to_new.setdefault(w['remove']['path'], old_to_new[w['keep']['path']])

    warnings: list[str] = []
    removals: list[dict] = []
    detail = 'identical album (keeper chosen in review)'
    for t in folders[old_keep]['tracks']:
        if t.get('error'):
            raise DecisionError(f"{old_keep} has an unreadable file, so it can't be removed")
        target = old_to_new.get(t['path'])
        if target is None:
            raise DecisionError(f"{new_keep} has no copy of {t['path']}")
        if _quality(tracks[target]) < _quality(t):
            warnings.append(f"{t['path']} ({t['quality']}) would be replaced by a lower-quality copy "
                            f"({tracks[target]['quality']})")
        removals.append({**_ref(t), 'keep': _ref(tracks[target]), 'reason': 'duplicate-album',
                         'group': gid, 'detail': detail})
    removals += [{**e, 'keep': None, 'reason': 'extra', 'group': gid,
                  'detail': 'non-audio file in a removed folder'} for e in folders[old_keep]['extras']]

    for folder, mapping in to_old.items():
        if folder == new_keep:
            continue
        pairs = {p: old_to_new.get(o) for p, o in mapping.items()}
        if not pairs or None in pairs.values():
            warnings.append(f"{folder} is kept: {new_keep} doesn't hold all of its tracks")
            continue
        for p, target in sorted(pairs.items()):
            removals.append({**_ref(tracks[p]), 'keep': _ref(tracks[target]),
                             'reason': f"{members[folder]['kind']}-album", 'group': gid, 'detail': detail})
        removals += [r for r in plan['removals'] if r.get('group') == gid and r['reason'] == 'extra'
                     and os.path.dirname(r['path']) == folder]
    return removals, warnings


def apply_decisions(plan: dict, decisions: dict) -> tuple[dict, list[str]]:
    """Returns (new plan, warnings). The new plan contains only decided removals."""
    groups = {str(g['id']): g for g in plan['groups']}
    removals: list[dict] = []
    warnings: list[str] = []
    new_groups = []
    for gid, choice in (decisions.get('groups') or {}).items():
        group = groups.get(str(gid))
        if group is None:
            raise DecisionError(f"unknown group {gid}")
        if choice == 'skip':
            continue
        if choice == 'accept':
            removals += [r for r in plan['removals'] if r.get('group') == group['id']]
            new_groups.append(group)
        elif isinstance(choice, dict) and 'keep' in choice:
            if choice['keep'] == group['keep']:
                removals += [r for r in plan['removals'] if r.get('group') == group['id']]
                new_groups.append(group)
                continue
            rs, ws = _rekeep(plan, group, choice['keep'])
            removals += rs
            warnings += ws
            kept_now = {os.path.dirname(r['path']) for r in rs}
            old = plan['folders'][group['keep']]['tracks']
            new_groups.append({**group, 'keep': choice['keep'], 'remove': [
                *(m for m in group['remove'] if m['folder'] != choice['keep'] and m['folder'] in kept_now),
                {'folder': group['keep'], 'kind': 'duplicate', 'tracks': len(old),
                 'bytes': sum(t['size'] for t in old)}]})
        else:
            raise DecisionError(f"bad decision for group {gid}: {choice!r}")

    within = set(decisions.get('within') or [])
    removals += [r for r in plan['removals'] if r['reason'] == 'within-folder' and r['path'] in within]

    # Never keep a file that another decision removes.
    paths = {r['path'] for r in removals}
    conflicts = [r for r in removals if r.get('keep') and r['keep']['path'] in paths]
    if conflicts:
        raise DecisionError("these decisions conflict: a kept file would also be removed "
                            f"({conflicts[0]['keep']['path']})")

    new = copy.deepcopy(plan)
    new['groups'] = new_groups
    new['removals'] = sorted(removals, key=lambda r: r['path'])
    new['summary'] = {**plan['summary'],
                      'duplicate_folders': sum(len(g['remove']) for g in new_groups),
                      'files_to_remove': len(removals),
                      'audio_files_to_remove': sum(1 for r in removals if r['reason'] != 'extra'),
                      'bytes_to_free': sum(r['size'] for r in removals)}
    new['decided'] = True
    return new, warnings
