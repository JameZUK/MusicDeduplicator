import errno
import json
import os

import pytest
from conftest import make_fp

from musicdedup import executor
from musicdedup.executor import PlanError, apply_plan, load_plan, undo


def snapshot(root: str) -> dict[str, bytes]:
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, 'rb') as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


@pytest.fixture
def dup_lib(lib):
    lib.album('A/Album', [1, 2, 3])
    lib.album('B/Album', [1, 2, 3])
    lib.extra('B/Album/cover.jpg')
    return lib


def test_move_then_undo_restores_everything(dup_lib, tmp_path):
    before = snapshot(dup_lib.root)
    _, _, plan = dup_lib.scan()
    q = str(tmp_path / 'quarantine')
    result = apply_plan(plan, mode='move', move_to=q)
    assert result.counts['moved'] == 4 and not result.skipped
    assert not os.path.exists(dup_lib.path('B/Album'))           # emptied folder removed
    assert not os.path.exists(dup_lib.path('B'))
    assert os.path.exists(os.path.join(q, 'music', 'B', 'Album', '01.flac'))
    assert snapshot(dup_lib.path('A')) == {k[2:]: v for k, v in before.items() if k.startswith('A/')}

    restored = undo(result.journal)
    assert restored.counts['restored'] == 4
    assert snapshot(dup_lib.root) == before
    assert not os.path.exists(os.path.join(q, 'music'))         # quarantine tidied


def test_dry_run_changes_nothing(dup_lib, tmp_path):
    before = snapshot(dup_lib.root)
    _, _, plan = dup_lib.scan()
    result = apply_plan(plan, mode='move', move_to=str(tmp_path / 'q'), dry_run=True)
    assert result.counts['moved'] == 4
    assert snapshot(dup_lib.root) == before
    assert not os.path.exists(tmp_path / 'q')
    result = apply_plan(plan, mode='delete', dry_run=True)
    assert snapshot(dup_lib.root) == before


def test_changed_file_is_skipped(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    with open(dup_lib.path('B/Album/02.flac'), 'ab') as f:
        f.write(b'new data')
    result = apply_plan(plan, mode='delete', journal_path=str(tmp_path / 'j.jsonl'))
    assert os.path.exists(dup_lib.path('B/Album/02.flac'))
    assert ('changed since the scan' in dict(result.skipped)[dup_lib.path('B/Album/02.flac')])
    # Its folder still has audio, so the artwork stays too.
    assert os.path.exists(dup_lib.path('B/Album/cover.jpg'))


def test_missing_keeper_is_skipped(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    os.remove(dup_lib.path('A/Album/01.flac'))
    result = apply_plan(plan, mode='delete', journal_path=str(tmp_path / 'j.jsonl'))
    assert os.path.exists(dup_lib.path('B/Album/01.flac'))
    assert 'copy to keep' in dict(result.skipped)[dup_lib.path('B/Album/01.flac')]


def test_file_replaced_by_symlink_is_skipped(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    p = dup_lib.path('B/Album/01.flac')
    os.remove(p)
    os.symlink(dup_lib.path('A/Album/01.flac'), p)
    result = apply_plan(plan, mode='delete', journal_path=str(tmp_path / 'j.jsonl'))
    assert os.path.exists(dup_lib.path('A/Album/01.flac'))
    assert 'symlink' in dict(result.skipped)[p]


def test_new_audio_in_folder_keeps_extras(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    dup_lib.add('B/Album/04 new rip.flac', make_fp(50))
    apply_plan(plan, mode='delete', journal_path=str(tmp_path / 'j.jsonl'))
    assert os.path.exists(dup_lib.path('B/Album/04 new rip.flac'))
    assert os.path.exists(dup_lib.path('B/Album/cover.jpg'))


def test_moves_never_overwrite(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    q = tmp_path / 'q'
    target = q / 'music' / 'B' / 'Album'
    target.mkdir(parents=True)
    (target / '01.flac').write_bytes(b'from an earlier run')
    apply_plan(plan, mode='move', move_to=str(q))
    assert (target / '01.flac').read_bytes() == b'from an earlier run'
    assert (target / '01 (2).flac').exists()


def test_destination_inside_library_is_refused(dup_lib):
    _, _, plan = dup_lib.scan()
    with pytest.raises(PlanError):
        apply_plan(plan, mode='move', move_to=dup_lib.path('Duplicates'))


def test_tampered_plan_outside_roots_is_skipped(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    outside = tmp_path / 'precious.flac'
    outside.write_bytes(b'x')
    st = outside.stat()
    plan['removals'].append({'path': str(outside), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
                             'keep': None, 'reason': 'extra'})
    apply_plan(plan, mode='delete', journal_path=str(tmp_path / 'j.jsonl'))
    assert outside.exists()


def test_inconsistent_plan_never_removes_both_copies(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    r = next(r for r in plan['removals'] if r['keep'])
    plan['removals'].append({**r['keep'], 'keep': {k: r[k] for k in ('path', 'size', 'mtime_ns')},
                             'reason': 'duplicate-album'})
    apply_plan(plan, mode='delete', journal_path=str(tmp_path / 'j.jsonl'))
    assert os.path.exists(r['path']) and os.path.exists(r['keep']['path'])


def test_delete_writes_journal(dup_lib, tmp_path):
    _, _, plan = dup_lib.scan()
    j = tmp_path / 'deleted.jsonl'
    result = apply_plan(plan, mode='delete', journal_path=str(j))
    assert result.counts['deleted'] == 4
    entries = [json.loads(line) for line in j.read_text().splitlines()]
    assert entries[0]['op'] == 'start'
    assert sum(1 for e in entries if e['op'] == 'delete') == 4
    assert undo(str(j)).counts['deleted (cannot be restored)'] == 4


def test_load_plan_rejects_other_files(tmp_path):
    p = tmp_path / 'x.json'
    p.write_text('{"format": "something else"}')
    with pytest.raises(PlanError):
        load_plan(str(p))


def test_move_file_without_hard_link_support(tmp_path, monkeypatch):
    src, dst = tmp_path / 'a.flac', tmp_path / 'sub' / 'a.flac'
    src.write_bytes(b'audio')

    def no_links(a, b):
        raise OSError(errno.EPERM, 'not supported')

    monkeypatch.setattr(executor.os, 'link', no_links)
    executor.move_file(str(src), str(dst))
    assert dst.read_bytes() == b'audio' and not src.exists()
    src.write_bytes(b'other')
    with pytest.raises(FileExistsError):
        executor.move_file(str(src), str(dst))
    assert dst.read_bytes() == b'audio'


def test_move_file_across_filesystems(tmp_path, monkeypatch):
    src, dst = tmp_path / 'a.flac', tmp_path / 'other' / 'a.flac'
    src.write_bytes(b'audio' * 1000)
    real_stat = os.stat

    def cross_device(a, b):
        raise OSError(errno.EXDEV, 'cross-device link')

    class FakeStat:
        def __init__(self, st, dev):
            self._st, self.st_dev = st, dev

        def __getattr__(self, name):
            return getattr(self._st, name)

    def fake_stat(p, *a, **k):
        st = real_stat(p, *a, **k)
        return FakeStat(st, 1 if str(p).startswith(str(tmp_path / 'other')) else 2)

    monkeypatch.setattr(executor.os, 'link', cross_device)
    monkeypatch.setattr(executor.os, 'stat', fake_stat)
    executor.move_file(str(src), str(dst))
    assert dst.read_bytes() == b'audio' * 1000 and not src.exists()
