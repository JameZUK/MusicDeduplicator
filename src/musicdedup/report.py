"""Human-readable summary of a plan."""

from __future__ import annotations

import os


def human_bytes(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024 or unit == 'TB':
            return f"{n:.0f} {unit}" if unit == 'B' else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _rel(path: str, roots: list[str]) -> str:
    for r in roots:
        if path == r or path.startswith(r.rstrip(os.sep) + os.sep):
            rel = os.path.relpath(path, r)
            return rel if len(roots) == 1 else os.path.join(os.path.basename(r), rel)
    return path


def format_report(plan: dict, limit: int | None = 25) -> str:
    roots = plan['roots']
    s = plan['summary']
    out: list[str] = []
    add = out.append

    def capped(items: list) -> list:
        return items if limit is None else items[:limit]

    def more(items: list) -> None:
        if limit is not None and len(items) > limit:
            add(f"    … and {len(items) - limit} more (see the plan file, or use --full-report)")

    add(f"Scanned {s['audio_files']} audio files in {s['folders']} folders.")
    skipped = [f"{s[k]} {k}" for k in ('symlinked files', 'symlinked folders', 'hard-linked files',
                                       'hidden or system folders', 'excluded folders',
                                       'unreadable folders') if s.get(k)]
    if skipped:
        add("Skipped: " + ', '.join(skipped) + '.')
    add('')

    groups = plan['groups']
    if groups:
        add(f"Duplicate folders: {s['duplicate_folders']} folder(s) duplicate or are contained in another.")
        for g in capped(groups):
            add(f"  [{g['id']}] keep    {_rel(g['keep'], roots)}  ({g['keep_tracks']} tracks)")
            for r in g['remove']:
                what = 'same album' if r['kind'] == 'duplicate' else f"{r['tracks']} tracks, all in the kept folder"
                add(f"      remove  {_rel(r['folder'], roots)}  ({what}, {human_bytes(r['bytes'])})")
        more(groups)
    else:
        add("No duplicate folders found.")
    add('')

    within = plan['within_folder']
    if within:
        acting = plan['options']['within_folders']
        head = ("Duplicates inside a folder (will be removed):" if acting else
                "Duplicates inside a folder (reported only; add --within-folders to remove them):")
        add(head)
        for w in capped(within):
            add(f"  {_rel(w['remove']['path'], roots)}")
            add(f"      same audio as {os.path.basename(w['keep']['path'])}")
        more(within)
        add('')

    editions = plan['smaller_editions_kept']
    if editions:
        add("Kept intact: smaller editions whose tracks are all in a bigger edition"
            " (add --remove-smaller-editions to remove them):")
        for e in capped(editions):
            add(f"  {_rel(e['folder'], roots)}  ({e['edition']}, {e['tracks']} tracks)")
            add(f"      all in {_rel(e['contained_in'], roots)}  ({e['contained_in_edition']})")
        more(editions)
        add('')

    repeated = plan['repeated_in_release']
    if repeated:
        add("Kept intact: the same audio appears twice in a release's track list (e.g. a reprise or bonus repeat):")
        for r in capped(repeated):
            add(f"  {_rel(r['paths'][0], roots)}")
            add(f"  {_rel(r['paths'][1], roots)}")
        more(repeated)
        add('')

    if plan['blocked']:
        add("Duplicate folders that will NOT be removed, because something in them is unreadable:")
        for b in capped(plan['blocked']):
            add(f"  {_rel(b['folder'], roots)}  (copy of {_rel(b['copy_of'], roots)})")
            for p in b['problems'][:3]:
                add(f"      {p}")
        more(plan['blocked'])
        add('')

    variants = plan['edited_versions']
    if variants:
        add(f"Edited versions (same recording, different somewhere, e.g. explicit/clean): {len(variants)}."
            " These are never treated as duplicates.")
        for v in capped(variants)[:10]:
            a, b = v['paths']
            add(f"  {_rel(a, roots)}")
            add(f"  {_rel(b, roots)}  (differs around {v['differs_at']})")
        add('')

    shared = plan['shared_tracks']
    if shared:
        add(f"Folders sharing tracks but kept (compilations, deluxe editions, partial copies): {len(shared)} pairs.")
        for x in capped(shared)[:10]:
            a, b = x['folders']
            add(f"  {x['shared_tracks']} shared: {_rel(a, roots)} ({x['tracks'][0]})"
                f"  <->  {_rel(b, roots)} ({x['tracks'][1]})")
        add('')

    unreadable = plan['unreadable']
    if unreadable:
        add(f"Audio files that could not be read (possibly corrupt): {len(unreadable)}.")
        shown = unreadable if limit is None else unreadable[:10]
        for u in shown:
            add(f"  {_rel(u['path'], roots)}: {u['error']}")
        if len(shown) < len(unreadable):
            add(f"    … and {len(unreadable) - len(shown)} more (see the plan file, or use --full-report)")
        add('')

    add(f"Plan: remove {s['files_to_remove']} files ({s['audio_files_to_remove']} audio), "
        f"freeing {human_bytes(s['bytes_to_free'])}.")
    return '\n'.join(out)
