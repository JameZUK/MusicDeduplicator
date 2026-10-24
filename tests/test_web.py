import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest
from conftest import FLAC16, FLAC24

from musicdedup.web.access import AccessPolicy, Denied
from musicdedup.web.server import App, make_server

# -- access policy ---------------------------------------------------------------------


def test_lan_only_by_default():
    p = AccessPolicy()
    assert p.check('192.168.1.20', {'Host': '192.168.1.5:8650'}) is None
    assert p.check('::ffff:10.0.0.7', {'Host': 'localhost:8650'}) is None
    with pytest.raises(Denied):
        p.check('8.8.8.8', {'Host': '192.168.1.5:8650'})


def test_custom_allowlist():
    p = AccessPolicy(allow=['172.16.32.0/23'])
    p.check('172.16.33.4', {'Host': '172.16.32.102'})
    with pytest.raises(Denied):
        p.check('192.168.1.20', {'Host': '172.16.32.102'})


def test_dns_rebinding_host_is_refused():
    p = AccessPolicy(hostnames=['musicdedup.lan'])
    p.check('192.168.1.20', {'Host': 'musicdedup.lan:8650'})
    with pytest.raises(Denied):
        p.check('192.168.1.20', {'Host': 'attacker.example'})


def test_authelia_requires_proxy_and_user():
    p = AccessPolicy(mode='authelia', trusted_proxies=['172.16.32.10/32'])
    assert p.check('172.16.32.10', {'Remote-User': 'james'}) == 'james'
    with pytest.raises(Denied) as e:
        p.check('172.16.32.10', {})
    assert e.value.status == 401
    with pytest.raises(Denied):
        p.check('172.16.32.11', {'Remote-User': 'james'})   # header from anyone else is ignored
    with pytest.raises(ValueError):
        AccessPolicy(mode='authelia')


def test_csrf():
    p = AccessPolicy()
    with pytest.raises(Denied):
        p.check_write({'Host': 'localhost:1'})
    with pytest.raises(Denied):
        p.check_write({'Host': 'localhost:1', 'X-CSRF-Token': p.csrf_token, 'Origin': 'http://evil.example'})
    p.check_write({'Host': 'localhost:1', 'X-CSRF-Token': p.csrf_token, 'Origin': 'http://localhost:1'})


# -- server ------------------------------------------------------------------------------


@pytest.fixture
def server(lib, tmp_path):
    lib.album('A/Album hires', [1, 2, 3], FLAC24)
    lib.album('B/Album', [1, 2, 3], FLAC16)
    lib.extra('B/Album/cover.jpg', b'\xff\xd8jpeg')
    _, _, plan = lib.scan()
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(json.dumps(plan))
    q = tmp_path / 'quarantine'
    q.mkdir()
    app = App(str(plan_path), AccessPolicy(), state_dir=str(tmp_path / 'state'), cache_path=None,
              move_to=str(q), allow_delete=False)
    srv = make_server(app, '127.0.0.1', 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    token = json.load(urllib.request.urlopen(base + '/api/session'))['csrf']
    yield base, token, plan, lib, q
    srv.shutdown()
    srv.server_close()


def call(base, path, body=None, token=None, method=None, headers=None):
    req = urllib.request.Request(base + path, method=method or ('POST' if body is not None else 'GET'),
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', **(headers or {}),
                                          **({'X-CSRF-Token': token} if token else {})})
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read()
            return r.status, (json.loads(data) if r.headers['Content-Type'] == 'application/json' else data)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def wait_job(base, jid):
    for _ in range(100):
        _, job = call(base, f'/api/jobs/{jid}')
        if job['state'] != 'running':
            return job
        time.sleep(0.05)
    raise AssertionError('job did not finish')


def test_plan_and_group(server):
    base, _, plan, _, _ = server
    status, overview = call(base, '/api/plan')
    assert status == 200 and len(overview['groups']) == 1 and 'folders' not in overview
    gid = overview['groups'][0]['id']
    status, group = call(base, f'/api/group/{gid}')
    assert status == 200 and len(group['pairs']) == 3 and len(group['folders']) == 2


def test_only_plan_files_are_served(server):
    base, _, plan, lib, _ = server
    assert call(base, '/api/audio?path=/etc/passwd')[0] == 404
    assert call(base, '/api/cover?folder=/etc')[0] == 404
    assert call(base, '/api/compare?a=/etc/passwd&b=/etc/hosts')[0] == 404
    status, art = call(base, '/api/cover?folder=' + urllib.request.quote(os.path.realpath(lib.path('B/Album'))))
    assert status == 200 and art == b'\xff\xd8jpeg'


def test_audio_supports_ranges(server):
    base, _, plan, lib, _ = server
    path = os.path.realpath(lib.path('B/Album/01.flac'))
    data = open(path, 'rb').read()
    req = urllib.request.Request(base + '/api/audio?path=' + urllib.request.quote(path),
                                 headers={'Range': 'bytes=5-14'})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206 and r.read() == data[5:15]
        assert r.headers['Content-Range'] == f'bytes 5-14/{len(data)}'


def test_writes_need_the_csrf_token(server):
    base, token, *_ = server
    assert call(base, '/api/decisions', {'groups': {}}, method='PUT')[0] == 403
    assert call(base, '/api/decisions', {'groups': {}}, token=token, method='PUT',
                headers={'Origin': 'http://evil.example'})[0] == 403
    assert call(base, '/api/decisions', {'groups': {'1': 'accept'}}, token=token, method='PUT')[0] == 200
    assert call(base, '/api/decisions')[1]['groups'] == {'1': 'accept'}


def test_preview_apply_history_undo(server):
    base, token, plan, lib, q = server
    gid = str(plan['groups'][0]['id'])
    decisions = {'groups': {gid: 'accept'}}
    status, preview = call(base, '/api/preview', {'decisions': decisions}, token)
    assert status == 200 and preview['summary']['files_to_remove'] == 4
    status, started = call(base, '/api/apply', {'decisions': decisions, 'mode': 'move'}, token)
    assert status == 202
    job = wait_job(base, started['job'])
    assert job['state'] == 'done' and job['counts']['moved'] == 4
    assert not os.path.exists(lib.path('B/Album'))
    _, history = call(base, '/api/history')
    assert history[0]['op'] == 'apply' and history[0]['user'].endswith('(no login)')
    status, started = call(base, '/api/undo', {'journal': job['journal']}, token)
    assert wait_job(base, started['job'])['counts']['restored'] == 4
    assert os.path.exists(lib.path('B/Album/cover.jpg'))
    assert call(base, '/api/undo', {'journal': '/etc/passwd'}, token)[0] == 404


def test_delete_needs_server_flag_and_confirmation(server):
    base, token, plan, lib, _ = server
    decisions = {'groups': {str(plan['groups'][0]['id']): 'accept'}}
    status, err = call(base, '/api/apply', {'decisions': decisions, 'mode': 'delete', 'confirm': 'delete'}, token)
    assert status == 409 and '--allow-delete' in err['error']
    assert os.path.exists(lib.path('B/Album/01.flac'))


def test_nothing_applies_without_decisions(server):
    base, token, *_ = server
    assert call(base, '/api/apply', {'decisions': {}, 'mode': 'move'}, token)[0] == 400
