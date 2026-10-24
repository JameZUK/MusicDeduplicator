import os

from conftest import make_fp

from musicdedup.cache import Cache
from musicdedup.fingerprint import FingerprintTimeout


def test_symlinks_are_never_followed_or_matched(lib, tmp_path):
    lib.album('A/Album', [1, 2])
    os.makedirs(lib.path('Favourites'))
    for name in ('01.flac', '02.flac'):
        os.symlink(lib.path(f'A/Album/{name}'), lib.path(f'Favourites/{name}'))
    os.symlink(lib.path('A'), lib.path('Linked artist'))
    result, _, plan = lib.scan()
    assert len(result.tracks) == 2
    assert result.skipped['symlinked files'] == 2
    assert result.skipped['symlinked folders'] == 1
    assert plan['removals'] == []


def test_hard_links_are_not_duplicates(lib):
    lib.album('A/Album', [1, 2])
    os.makedirs(lib.path('B/Album'))
    for name in ('01.flac', '02.flac'):
        os.link(lib.path(f'A/Album/{name}'), lib.path(f'B/Album/{name}'))
    result, _, plan = lib.scan()
    assert result.skipped['hard-linked files'] == 2
    assert plan['removals'] == []


def test_appledouble_hidden_and_system_folders(lib):
    lib.album('A/Album', [1])
    lib.extra('A/Album/._01.flac', b'\x00\x05\x16\x07')
    lib.add('.Trash/old/01.flac', make_fp(1))
    lib.add('@eaDir/thumb/01.flac', make_fp(1))
    result, _, plan = lib.scan()
    assert [os.path.basename(t.path) for t in result.tracks] == ['01.flac']
    folder = result.folders[lib.path('A/Album')]
    assert [os.path.basename(e.path) for e in folder.extras] == ['._01.flac']
    assert plan['removals'] == []


def test_cache_avoids_refingerprinting_and_notices_changes(lib, tmp_path):
    lib.album('A/Album', [1, 2])
    cache = Cache(str(tmp_path / 'cache.db'))
    lib.scan(cache=cache)
    assert lib.fingerprint_calls == 2
    lib.scan(cache=cache)
    assert lib.fingerprint_calls == 2          # all from cache
    p = lib.path('A/Album/01.flac')
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1))  # 1 ns newer, same second
    lib.scan(cache=cache)
    assert lib.fingerprint_calls == 3
    cache.close()


def test_errors_are_cached_but_timeouts_are_not(lib, tmp_path):
    lib.add('A/bad.flac', None, error='not audio')
    lib.add('A/slow.flac', make_fp(1))
    real = lib.fingerprint

    def flaky(path):
        if path.endswith('slow.flac'):
            lib.fingerprint_calls += 1
            raise FingerprintTimeout('timed out')
        return real(path)

    lib.fingerprint = flaky
    cache = Cache(str(tmp_path / 'cache.db'))
    lib.scan(cache=cache)
    lib.scan(cache=cache)
    assert lib.fingerprint_calls == 3          # bad once (cached), slow twice (retried)
    cache.close()


def test_cache_schema_change_resets(tmp_path):
    import sqlite3
    path = str(tmp_path / 'c.db')
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE file_cache (file_path TEXT, metadata TEXT)')  # the old 1.x layout
    conn.commit()
    conn.close()
    cache = Cache(path)
    assert cache.stats()['entries'] == 0
    cache.put('/x.flac', 1, 2, 3.0, make_fp(1, 50), None, None)
    got = cache.get('/x.flac', 1, 2)
    assert got and (got.fingerprint == make_fp(1, 50)).all()
    assert cache.get('/x.flac', 1, 3) is None
    cache.close()


def test_cache_prune_removes_deleted_files(lib, tmp_path):
    lib.album('A/Album', [1, 2])
    cache = Cache(str(tmp_path / 'cache.db'))
    lib.scan(cache=cache)
    os.remove(lib.path('A/Album/02.flac'))
    result, _, _ = lib.scan(cache=cache)
    assert result.stats['stale cache entries pruned'] == 1
    assert cache.stats()['entries'] == 1
    cache.close()


def test_progress_is_logged_without_a_progress_bar(lib, monkeypatch, caplog):
    from musicdedup import scanner
    monkeypatch.setattr(scanner, 'PROGRESS_LOG_SECONDS', 0)
    lib.album('A/Album', [1, 2, 3])
    with caplog.at_level('INFO', logger='musicdedup.scanner'):
        lib.scan()
    assert any('Fingerprinted 3 of 3 files' in r.message for r in caplog.records)


def test_new_and_changed_files_are_tracked(lib, tmp_path):
    lib.album('A/Album', [1, 2])
    cache = Cache(str(tmp_path / 'cache.db'))
    _, _, plan = lib.scan(cache=cache)
    assert plan['new_music']['first_scan'] and plan['new_music']['new_tracks'] == 2
    lib.album('B/New Album', [7, 8, 9])
    p = lib.path('A/Album/01.flac')
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1))
    _, _, plan = lib.scan(cache=cache)
    nm = plan['new_music']
    assert not nm['first_scan'] and nm['new_tracks'] == 3 and nm['changed_tracks'] == 1
    assert {os.path.relpath(f['folder'], lib.root): (f['new'], f['changed']) for f in nm['folders']} == {
        'B/New Album': (3, 0), 'A/Album': (0, 1)}
    _, _, plan = lib.scan(cache=cache)
    assert plan['new_music']['folders'] == []
    cache.close()


def test_library_stats(lib):
    from conftest import FLAC24, MP3_320
    lib.album('A/Album', [1, 2], FLAC24, album='Album')
    lib.album('B/Other', [3], MP3_320, ext='mp3')
    _, _, plan = lib.scan()
    s = plan['library']
    assert s['tracks'] == 3 and s['albums'] == 2
    assert s['bit_depth'] == {'24-bit': 2} and s['lossy_bitrate'] == {'320 kbps and up': 1}
    assert s['duration_seconds'] > 0 and s['top_artists'][0]['tracks'] >= 1


def test_scan_can_be_cancelled(lib):
    import threading

    import pytest

    from musicdedup.scanner import ScanCancelled, scan
    lib.album('A/Album', [1, 2])
    stop = threading.Event()
    stop.set()
    with pytest.raises(ScanCancelled):
        scan([lib.root], Cache(None), fingerprint_fn=lib.fingerprint, info_fn=lib.info, cancel=stop)
