"""Carries out a plan: moves (default) or deletes planned files, and undoes moves.

Before touching a file it is re-checked against the plan: it must still be a
regular file (not a symlink) inside a scanned root, with the size and mtime it had
when scanned, and the copy being kept must still exist unchanged. Anything that
fails a check is skipped and reported. Moves never overwrite. Every action is
written to a journal as it happens, so an interrupted run can still be undone.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import shutil
import stat
import time
from collections import Counter
from dataclasses import dataclass, field

from .audio import is_audio
from .planner import PLAN_FORMAT, PLAN_VERSION
from .state import Busy, apply_lock, record_history

log = logging.getLogger(__name__)


class PlanError(Exception):
    """The plan or the requested action is unusable; nothing was changed."""


@dataclass
class Result:
    counts: Counter = field(default_factory=Counter)
    bytes_freed: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    journal: str | None = None


def load_plan(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            plan = json.load(f)
    except (OSError, ValueError) as e:
        raise PlanError(f"cannot read plan {path}: {e}") from e
    if plan.get('format') != PLAN_FORMAT or plan.get('version') != PLAN_VERSION:
        raise PlanError(f"{path} is not a musicdedup plan (version {PLAN_VERSION})")
    return plan


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _root_labels(roots: list[str]) -> dict[str, str]:
    labels, used = {}, set()
    for r in roots:
        base = os.path.basename(r.rstrip(os.sep)) or 'root'
        label, n = base, 2
        while label in used:
            label, n = f"{base}-{n}", n + 1
        used.add(label)
        labels[r] = label
    return labels


def _matches(ref: dict) -> str | None:
    """Returns why the file no longer matches the plan, or None if it does."""
    try:
        st = os.lstat(ref['path'])
    except FileNotFoundError:
        return 'no longer exists'
    except OSError as e:
        return f'cannot be read ({e.strerror})'
    if stat.S_ISLNK(st.st_mode):
        return 'is now a symlink'
    if not stat.S_ISREG(st.st_mode):
        return 'is no longer a regular file'
    if st.st_size != ref['size'] or st.st_mtime_ns != ref['mtime_ns']:
        return 'has changed since the scan'
    return None


def _unique_destination(dst: str) -> str:
    if not os.path.lexists(dst):
        return dst
    stem, ext = os.path.splitext(dst)
    n = 2
    while os.path.lexists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def move_file(src: str, dst: str) -> None:
    """Moves src to dst without ever replacing an existing dst."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)           # fails with EEXIST rather than overwriting
    except OSError as e:
        if e.errno == errno.EEXIST:
            raise
        if os.stat(src).st_dev == os.stat(os.path.dirname(dst)).st_dev:
            if os.path.lexists(dst):  # filesystem without hard links
                raise FileExistsError(errno.EEXIST, 'destination exists', dst) from e
            os.rename(src, dst)
            return
        # Different filesystem: exclusive-create copy, verify, then remove the source.
        with open(src, 'rb') as fin, open(dst, 'xb') as fout:
            shutil.copyfileobj(fin, fout, 1 << 20)
            fout.flush()
            os.fsync(fout.fileno())
        shutil.copystat(src, dst)
        if os.path.getsize(dst) != os.path.getsize(src):
            os.unlink(dst)
            raise OSError(errno.EIO, 'copy verification failed', dst) from e
        os.unlink(src)
        return
    try:
        os.unlink(src)
    except OSError:
        os.unlink(dst)
        raise


class _Journal:
    def __init__(self, path: str | None, header: dict):
        self.path = path
        self.f = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.f = open(path, 'x', encoding='utf-8')
            self.write({'op': 'start', **header})

    def write(self, entry: dict) -> None:
        if self.f:
            self.f.write(json.dumps(entry) + '\n')
            self.f.flush()

    def close(self) -> None:
        if self.f:
            self.f.close()


def apply_plan(plan: dict, *, mode: str, move_to: str | None = None, dry_run: bool = False,
               journal_path: str | None = None, state_dir: str | None = None,
               user: str | None = None) -> Result:
    """Carries out a plan. With state_dir, takes the shared apply lock (so the CLI
    and the dashboard never apply at once) and records the run in the history."""
    if state_dir is None or dry_run:
        return _apply_plan(plan, mode, move_to, dry_run, journal_path, user)
    try:
        with apply_lock(state_dir):
            result = _apply_plan(plan, mode, move_to, dry_run, journal_path, user)
    except Busy as e:
        raise PlanError(str(e)) from e
    record_history(state_dir, {'op': 'apply', 'mode': mode, 'journal': result.journal, 'user': user,
                               'plan_created': plan.get('created'), 'counts': dict(result.counts),
                               'bytes': result.bytes_freed, 'skipped': len(result.skipped)})
    return result


def _apply_plan(plan: dict, mode: str, move_to: str | None, dry_run: bool,
                journal_path: str | None, user: str | None) -> Result:
    if mode not in ('move', 'delete'):
        raise PlanError(f"unknown mode {mode!r}")
    roots = [os.path.realpath(r) for r in plan['roots']]
    for r in roots:
        if not os.path.isdir(r):
            raise PlanError(f"scanned folder {r} is not available")

    stamp = time.strftime('%Y%m%d-%H%M%S')
    labels = _root_labels(roots)
    if mode == 'move':
        if not move_to:
            raise PlanError("a destination folder is required to move duplicates")
        move_to = os.path.realpath(move_to)
        for r in roots:
            if _inside(move_to, r) or _inside(r, move_to):
                raise PlanError(f"the destination {move_to} must be outside the scanned folder {r}")
        journal_path = journal_path or os.path.join(move_to, f'musicdedup-journal-{stamp}.jsonl')
    else:
        journal_path = journal_path or os.path.abspath(f'musicdedup-deleted-{stamp}.jsonl')

    # Audio first, then extras (artwork etc.), so an extra is only removed once
    # every audio file in its folder has actually gone.
    removals = sorted(plan['removals'], key=lambda r: (r['reason'] == 'extra', r['path']))
    planned = {r['path'] for r in removals}
    result = Result(journal=None if dry_run else journal_path)
    gone: set[str] = set()   # removed, or would be in a dry run

    def folder_has_audio(d: str) -> bool:
        try:
            names = os.listdir(d)
        except OSError:
            return True
        return any(is_audio(n) and os.path.join(d, n) not in gone for n in names)

    journal = _Journal(None if dry_run else journal_path,
                       {'mode': mode, 'move_to': move_to, 'roots': roots, 'time': stamp,
                        'plan_created': plan.get('created'), 'user': user})
    verb = 'Would move' if dry_run and mode == 'move' else (
        'Would delete' if dry_run else ('Moved' if mode == 'move' else 'Deleted'))
    touched_dirs: set[str] = set()
    try:
        for r in removals:
            path = r['path']
            real_parent = os.path.realpath(os.path.dirname(path))
            root = next((x for x in roots if _inside(real_parent, x)), None)
            problem = None
            if root is None:
                problem = 'is outside the scanned folders'
            elif r['reason'] == 'extra' and folder_has_audio(os.path.dirname(path)):
                problem = 'its folder still has audio that is not being removed'
            else:
                problem = _matches(r)
                keep = r.get('keep')
                if problem is None and keep is not None:
                    if keep['path'] in planned:
                        problem = 'the copy to keep is also planned for removal (inconsistent plan)'
                    elif (why := _matches(keep)) is not None:
                        problem = f"the copy to keep ({keep['path']}) {why}"
            if problem:
                result.skipped.append((path, problem))
                result.counts['skipped'] += 1
                log.warning("Skipping %s: %s", path, problem)
                continue

            if mode == 'move':
                dst = _unique_destination(os.path.join(move_to, labels[root], os.path.relpath(path, root)))
                if dry_run:
                    log.info("%s %s -> %s", verb, path, dst)
                else:
                    try:
                        move_file(path, dst)
                    except OSError as e:
                        result.skipped.append((path, f'move failed: {e}'))
                        result.counts['failed'] += 1
                        log.error("Could not move %s: %s", path, e)
                        continue
                    journal.write({'op': 'move', 'src': path, 'dst': dst, 'size': r['size']})
                    log.info("%s %s -> %s", verb, path, dst)
            else:
                if dry_run:
                    log.info("%s %s", verb, path)
                else:
                    try:
                        os.unlink(path)
                    except OSError as e:
                        result.skipped.append((path, f'delete failed: {e}'))
                        result.counts['failed'] += 1
                        log.error("Could not delete %s: %s", path, e)
                        continue
                    journal.write({'op': 'delete', 'path': path, 'size': r['size'],
                                   'kept': (r.get('keep') or {}).get('path')})
                    log.info("%s %s", verb, path)
            gone.add(path)
            result.counts['moved' if mode == 'move' else 'deleted'] += 1
            result.bytes_freed += r['size']
            touched_dirs.add(os.path.dirname(path))

        if not dry_run:
            for d in sorted(touched_dirs, key=len, reverse=True):
                root = next(x for x in roots if _inside(os.path.realpath(d), x))
                while _inside(d, root) and d != root:
                    try:
                        os.rmdir(d)  # only succeeds if empty
                    except OSError:
                        break
                    journal.write({'op': 'rmdir', 'path': d})
                    result.counts['empty folders removed'] += 1
                    d = os.path.dirname(d)
    finally:
        journal.close()
    return result


def undo(journal_path: str, dry_run: bool = False, state_dir: str | None = None,
         user: str | None = None) -> Result:
    """Moves files back to where they came from, newest first. Never overwrites."""
    if state_dir is None or dry_run:
        return _undo(journal_path, dry_run)
    try:
        with apply_lock(state_dir):
            result = _undo(journal_path, dry_run)
    except Busy as e:
        raise PlanError(str(e)) from e
    record_history(state_dir, {'op': 'undo', 'journal': journal_path, 'user': user,
                               'counts': dict(result.counts), 'skipped': len(result.skipped)})
    return result


def _undo(journal_path: str, dry_run: bool) -> Result:
    try:
        with open(journal_path, encoding='utf-8') as f:
            entries = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError) as e:
        raise PlanError(f"cannot read journal {journal_path}: {e}") from e
    if not entries or entries[0].get('op') != 'start':
        raise PlanError(f"{journal_path} is not a musicdedup journal")
    move_to = entries[0].get('move_to')
    result = Result()
    for e in reversed(entries[1:]):
        op = e.get('op')
        if op == 'rmdir':
            if not dry_run:
                os.makedirs(e['path'], exist_ok=True)
        elif op == 'move':
            src, dst = e['src'], e['dst']
            if os.path.lexists(src):
                result.skipped.append((src, 'something already exists at the original location'))
                result.counts['skipped'] += 1
            elif not os.path.lexists(dst):
                result.skipped.append((src, f'moved copy {dst} is missing'))
                result.counts['skipped'] += 1
            else:
                if not dry_run:
                    try:
                        move_file(dst, src)
                    except OSError as err:
                        result.skipped.append((src, f'restore failed: {err}'))
                        result.counts['failed'] += 1
                        continue
                    d = os.path.dirname(dst)
                    while move_to and _inside(d, move_to) and d != move_to:
                        try:
                            os.rmdir(d)
                        except OSError:
                            break
                        d = os.path.dirname(d)
                log.info("%s %s", 'Would restore' if dry_run else 'Restored', src)
                result.counts['restored'] += 1
                result.bytes_freed += e.get('size', 0)
        elif op == 'delete':
            result.counts['deleted (cannot be restored)'] += 1
    return result
