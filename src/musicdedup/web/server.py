"""HTTP server for the dashboard. Standard library only.

The dashboard reviews one plan file. Audio, artwork and comparisons are served
only for paths the plan contains, never arbitrary files. Applying goes through
the same executor as the CLI (re-checks, journal, shared lock, history).
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..art import IMAGE_TYPES, embedded_cover, find_cover_file
from ..cache import Cache
from ..decisions import DecisionError, apply_decisions
from ..executor import PlanError, apply_plan, load_plan, undo
from ..fingerprint import FingerprintError, compare_profile, run_fpcalc
from ..pipeline import run_scan
from ..planner import Options
from ..scanner import ScanCancelled
from ..state import read_history, read_scans
from ..waveform import WaveformError, waveform
from .access import AccessPolicy, Denied

log = logging.getLogger(__name__)

SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; "
                               "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'same-origin',
    'X-Frame-Options': 'DENY',
}
MAX_BODY = 4 * 1024 * 1024


class App:
    """Everything the handlers share: the plan, settings, cache and jobs."""

    def __init__(self, plan_path: str, policy: AccessPolicy, *, state_dir: str, cache_path: str | None,
                 move_to: str | None, allow_delete: bool, library: list[str] | None = None,
                 excludes: list[str] | None = None, scan_options: Options | None = None,
                 workers: int | None = None):
        self.plan_path = os.path.abspath(plan_path)
        self.policy = policy
        self.state_dir = state_dir
        self.cache_path = cache_path
        self.move_to = move_to
        self.allow_delete = allow_delete
        self.library = library or []
        self.excludes = excludes or []
        self.scan_options = scan_options or Options()
        self.workers = workers
        self.jobs: dict[str, dict] = {}
        self.scan_state: dict = {'state': 'idle'}
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._plan_mtime = None
        self.plan: dict | None = None
        self.plan_id: str | None = None
        self.tracks: dict = {}
        self.reload()

    # -- plan ---------------------------------------------------------------------

    def reload(self) -> None:
        """Loads the plan if it is new or has changed. A missing plan is fine: the
        dashboard then says a scan is needed (or running) and picks it up later."""
        try:
            mtime = os.path.getmtime(self.plan_path)
        except FileNotFoundError:
            return
        with self._lock:
            if mtime == self._plan_mtime:
                return
            plan = load_plan(self.plan_path)
            previous, previous_id = self.plan, self.plan_id
            self.plan = plan
            self._plan_mtime = mtime
            self.tracks = {t['path']: t for f in plan.get('folders', {}).values() for t in f['tracks']}
            self.plan_id = hashlib.sha256(f"{plan['created']}|{self.plan_path}".encode()).hexdigest()[:16]
            if previous is not None and previous_id != self.plan_id:
                self._carry_decisions(previous, previous_id)

    def require_plan(self) -> dict:
        self.reload()
        if self.plan is None:
            raise Denied(503, "no plan yet: run a scan")
        return self.plan

    @staticmethod
    def _signature(group: dict) -> str:
        return '\0'.join([group['keep'], *sorted(r['folder'] for r in group['remove'])])

    def _carry_decisions(self, previous: dict, previous_id: str) -> None:
        """A rescan makes a new plan; keep each decision whose group is unchanged."""
        if os.path.exists(self._decisions_path()):
            return
        try:
            with open(os.path.join(self.state_dir, f'decisions-{previous_id}.json'), encoding='utf-8') as f:
                old = json.load(f)
        except (OSError, ValueError):
            return
        by_sig = {self._signature(g): old.get('groups', {}).get(str(g['id']))
                  for g in previous['groups']}
        groups = {}
        for g in self.plan['groups']:
            choice = by_sig.get(self._signature(g))
            members = {g['keep'], *(r['folder'] for r in g['remove'])}
            if choice in ('accept', 'skip') or (isinstance(choice, dict) and choice.get('keep') in members):
                groups[str(g['id'])] = choice
        within_now = {w['remove']['path'] for w in self.plan.get('within_folder', [])}
        self.save_decisions({'groups': groups,
                             'within': [p for p in old.get('within', []) if p in within_now]})

    def overview(self) -> dict:
        p = self.require_plan()
        groups = []
        for g in p['groups']:
            keep = p['folders'].get(g['keep'], {})
            removes = [{**r, 'quality': _folder_quality(p['folders'].get(r['folder'], {})),
                        'lossy': _all_lossy(p['folders'].get(r['folder'], {}))} for r in g['remove']]
            groups.append({**g, 'remove': removes, 'keep_release': keep.get('release'),
                           'keep_quality': _folder_quality(keep),
                           'identical': all(r['kind'] == 'duplicate' for r in g['remove']),
                           'only_lossy_removed': all(r['lossy'] for r in removes),
                           'bytes': sum(r['bytes'] for r in g['remove'])})
        keys = ('created', 'roots', 'options', 'summary', 'smaller_editions_kept', 'repeated_in_release',
                'blocked', 'edited_versions', 'shared_tracks', 'unreadable', 'within_folder')
        extra = {k: p.get(k) for k in ('library', 'new_music', 'scan_seconds')}
        return {k: p[k] for k in keys} | extra | {'groups': groups, 'plan_id': self.plan_id}

    def group(self, gid: int) -> dict:
        self.require_plan()
        g = next((g for g in self.plan['groups'] if g['id'] == gid), None)
        if g is None:
            raise Denied(404, "no such group")
        folders = [g['keep'], *(r['folder'] for r in g['remove'])]
        pairs = [{'remove': r['path'], 'keep': r['keep']['path']}
                 for r in self.plan['removals'] if r.get('group') == gid and r.get('keep')]
        return {'group': g, 'folders': {f: self.plan['folders'].get(f) for f in folders}, 'pairs': pairs}

    def folder(self, path: str) -> dict:
        f = self.require_plan()['folders'].get(path)
        if f is None:
            raise Denied(404, "folder is not part of this plan")
        return f

    # -- decisions (kept server-side so they survive reloads and other devices) ----

    def _decisions_path(self) -> str:
        return os.path.join(self.state_dir, f'decisions-{self.plan_id}.json')

    def load_decisions(self) -> dict:
        try:
            with open(self._decisions_path(), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {'groups': {}, 'within': []}

    def save_decisions(self, decisions: dict) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self._decisions_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(decisions, f)
        os.replace(tmp, self._decisions_path())

    # -- comparisons ---------------------------------------------------------------

    def fingerprint(self, path: str):
        t = self.tracks.get(path)
        if t is None:
            raise Denied(404, "track is not part of this plan")
        if self.cache_path:
            cache = Cache(self.cache_path)
            try:
                hit = cache.get(path, t['size'], t['mtime_ns'])
            finally:
                cache.close()
            if hit and hit.fingerprint is not None:
                return hit.fingerprint
        try:
            return run_fpcalc(path)[1]
        except FingerprintError as e:
            raise Denied(422, f"cannot fingerprint: {e}") from e

    def compare(self, a: str, b: str) -> dict:
        profile = compare_profile(self.fingerprint(a), self.fingerprint(b))
        return profile or {'kind': 'different'}

    # -- scanning ------------------------------------------------------------------

    @property
    def scanning(self) -> bool:
        return self.scan_state.get('state') == 'running'

    def start_scan(self, user: str | None) -> None:
        if not self.library:
            raise Denied(409, "rescanning is not configured: start the server with --library")
        if self.scanning:
            raise Denied(409, "a scan is already running")
        if any(j['state'] == 'running' for j in self.jobs.values()):
            raise Denied(409, "wait for the current apply or undo to finish")
        self._cancel.clear()
        st = {'state': 'running', 'stage': 'starting', 'done': 0, 'total': 0, 'started': time.time(),
              'user': user}
        self.scan_state = st

        def progress(stage: str, done: int, total: int) -> None:
            st.update(stage=stage, done=done, total=total)

        def run():
            try:
                plan = run_scan(self.library, plan_path=self.plan_path, cache_path=self.cache_path,
                                options=self.scan_options, excludes=self.excludes, workers=self.workers,
                                on_progress=progress, cancel=self._cancel, state_dir=self.state_dir)
                st.update(state='done', summary={
                    'tracks': plan['summary']['audio_files'],
                    'new': plan['new_music']['new_tracks'], 'changed': plan['new_music']['changed_tracks'],
                    'duplicate_folders': plan['summary']['duplicate_folders']})
                self.reload()
            except ScanCancelled:
                st.update(state='cancelled')
            except Exception as e:  # report, never crash the server
                log.exception("scan failed")
                st.update(state='failed', error=str(e))
            st['finished'] = time.time()

        threading.Thread(target=run, daemon=True, name='scan').start()

    def cancel_scan(self) -> None:
        if not self.scanning:
            raise Denied(409, "no scan is running")
        self._cancel.set()

    # -- jobs ----------------------------------------------------------------------

    def start_job(self, kind: str, fn) -> str:
        jid = uuid.uuid4().hex[:12]
        job = {'id': jid, 'kind': kind, 'state': 'running', 'started': time.time()}
        self.jobs[jid] = job

        def run():
            try:
                result = fn()
                job.update(state='done', counts=dict(result.counts), bytes=result.bytes_freed,
                           skipped=[{'path': p, 'reason': r} for p, r in result.skipped[:500]],
                           journal=result.journal)
            except (PlanError, DecisionError) as e:
                job.update(state='failed', error=str(e))
            except Exception as e:  # report, never crash the server
                log.exception("job %s failed", jid)
                job.update(state='failed', error=f"unexpected error: {e}")
            job['finished'] = time.time()

        threading.Thread(target=run, daemon=True).start()
        return jid


def _all_lossy(folder: dict) -> bool:
    tracks = folder.get('tracks', [])
    return bool(tracks) and not any(t.get('lossless') for t in tracks)


def _folder_quality(folder: dict) -> str:
    qualities = sorted({t.get('quality', 'unknown') for t in folder.get('tracks', [])})
    return ', '.join(qualities[:2]) + (' …' if len(qualities) > 2 else '')


class Handler(BaseHTTPRequestHandler):
    server_version = f'musicdedup/{__version__}'
    app: App  # set on the subclass made by make_server

    # -- plumbing -------------------------------------------------------------------

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.client_address[0], fmt % args)

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data).encode(), 'application/json', {'Cache-Control': 'no-store'})

    def _error(self, status: int, message: str):
        self._json({'error': message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            raise Denied(413, "request too large")
        try:
            return json.loads(self.rfile.read(length) or b'{}')
        except ValueError as e:
            raise Denied(400, "invalid JSON") from e

    def _dispatch(self, write: bool):
        app = self.app
        try:
            self.user = app.policy.check(self.client_address[0], self.headers)
            if write:
                app.policy.check_write(self.headers)
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            route = self.WRITE_ROUTES if write else self.READ_ROUTES
            for pattern, name in route:
                m = re.fullmatch(pattern, url.path)
                if m:
                    return getattr(self, name)(q, *m.groups())
            if not write:
                return self._static(url.path)
            raise Denied(404, "not found")
        except Denied as e:
            self._error(e.status, str(e))
        except (PlanError, DecisionError) as e:
            self._error(409, str(e))
        except BrokenPipeError:
            pass
        except Exception:
            log.exception("error handling %s", self.path)
            self._error(500, "internal error")

    def do_GET(self):  # noqa: N802
        self._dispatch(write=False)

    def do_HEAD(self):  # noqa: N802
        self._dispatch(write=False)

    def do_POST(self):  # noqa: N802
        self._dispatch(write=True)

    def do_PUT(self):  # noqa: N802
        self._dispatch(write=True)

    READ_ROUTES = [
        (r'/api/session', 'get_session'),
        (r'/api/plan', 'get_plan'),
        (r'/api/group/(\d+)', 'get_group'),
        (r'/api/folder', 'get_folder'),
        (r'/api/compare', 'get_compare'),
        (r'/api/cover', 'get_cover'),
        (r'/api/audio', 'get_audio'),
        (r'/api/waveform', 'get_waveform'),
        (r'/api/decisions', 'get_decisions'),
        (r'/api/history', 'get_history'),
        (r'/api/jobs/([0-9a-f]+)', 'get_job'),
        (r'/api/scan', 'get_scan'),
        (r'/api/scans', 'get_scans'),
    ]
    WRITE_ROUTES = [
        (r'/api/decisions', 'put_decisions'),
        (r'/api/preview', 'post_preview'),
        (r'/api/apply', 'post_apply'),
        (r'/api/undo', 'post_undo'),
        (r'/api/scan', 'post_scan'),
        (r'/api/scan/cancel', 'post_scan_cancel'),
    ]

    # -- reads ------------------------------------------------------------------------

    def get_session(self, q):
        app = self.app
        app.reload()
        self._json({'csrf': app.policy.csrf_token, 'user': self.user, 'auth': app.policy.mode,
                    'version': __version__, 'move_to': app.move_to, 'allow_delete': app.allow_delete,
                    'plan_path': app.plan_path, 'has_plan': app.plan is not None,
                    'can_scan': bool(app.library), 'library': app.library})

    def get_plan(self, q):
        self.app.reload()
        self._json(self.app.overview())

    def get_group(self, q, gid):
        self._json(self.app.group(int(gid)))

    def get_folder(self, q):
        self._json(self.app.folder(q.get('path', '')))

    def get_compare(self, q):
        self._json(self.app.compare(q.get('a', ''), q.get('b', '')))

    def get_decisions(self, q):
        self._json(self.app.load_decisions())

    def get_history(self, q):
        self._json(list(reversed(read_history(self.app.state_dir)))[:200])

    def get_scan(self, q):
        self._json(self.app.scan_state)

    def get_scans(self, q):
        self._json(list(reversed(read_scans(self.app.state_dir)))[:100])

    def post_scan(self, q):
        self.app.start_scan(self.user or f"{self.client_address[0]} (no login)")
        self._json(self.app.scan_state, 202)

    def post_scan_cancel(self, q):
        self.app.cancel_scan()
        self._json({'ok': True})

    def get_job(self, q, jid):
        job = self.app.jobs.get(jid)
        if job is None:
            raise Denied(404, "no such job")
        self._json(job)

    def get_waveform(self, q):
        t = self.app.tracks.get(q.get('path', ''))
        if t is None:
            raise Denied(404, "track is not part of this plan")
        try:
            data = waveform(t['path'], t['size'], t['mtime_ns'])
        except WaveformError as e:
            raise Denied(422, f"no waveform: {e}") from e
        self._send(200, json.dumps(data).encode(), 'application/json', {'Cache-Control': 'private, max-age=3600'})

    def get_cover(self, q):
        folder = q.get('folder', '')
        f = self.app.folder(folder)
        path = find_cover_file(folder)
        if path:
            with open(path, 'rb') as fh:
                data = fh.read()
            ctype = IMAGE_TYPES[os.path.splitext(path)[1].lower()]
        else:
            found = next(filter(None, (embedded_cover(t['path']) for t in f['tracks'])), None)
            if not found:
                raise Denied(404, "no artwork")
            data, ctype = found
        self._send(200, data, ctype, {'Cache-Control': 'private, max-age=3600'})

    def get_audio(self, q):
        path = q.get('path', '')
        t = self.app.tracks.get(path)
        if t is None:
            raise Denied(404, "track is not part of this plan")
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        if path.lower().endswith('.flac'):
            ctype = 'audio/flac'
        start, end, status = 0, size - 1, 200
        rng = self.headers.get('Range')
        if rng:
            m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip())
            if not m or (not m.group(1) and not m.group(2)):
                raise Denied(416, "bad range")
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                raise Denied(416, "bad range")
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(path, 'rb') as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _static(self, path: str):
        root = resources.files('musicdedup.web') / 'static'
        rel = path.lstrip('/') or 'index.html'
        if '..' in rel.split('/'):
            raise Denied(404, "not found")
        target = root / rel
        if not target.is_file():
            target = root / 'index.html'  # single-page app routes
            if not target.is_file():
                raise Denied(404, "dashboard assets are not built (run npm run build in web/)")
        ctype = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        cache = 'public, max-age=31536000, immutable' if rel.startswith('assets/') else 'no-cache'
        self._send(200, target.read_bytes(), ctype, {'Cache-Control': cache})

    # -- writes -----------------------------------------------------------------------

    def put_decisions(self, q):
        body = self._body()
        decisions = {'groups': dict(body.get('groups') or {}), 'within': list(body.get('within') or [])}
        self.app.save_decisions(decisions)
        self._json({'ok': True})

    def post_preview(self, q):
        new, warnings = apply_decisions(self.app.require_plan(), self._body().get('decisions') or {})
        self._json({'summary': new['summary'], 'warnings': warnings, 'removals': new['removals'][:2000],
                    'groups': new['groups']})

    def post_apply(self, q):
        app = self.app
        body = self._body()
        mode = body.get('mode')
        if mode == 'move':
            if not app.move_to:
                raise Denied(409, "moving is not configured: start the server with --move-to")
        elif mode == 'delete':
            if not app.allow_delete:
                raise Denied(409, "deleting is not enabled: start the server with --allow-delete")
            if body.get('confirm') != 'delete':
                raise Denied(400, "type 'delete' to confirm")
        else:
            raise Denied(400, "mode must be 'move' or 'delete'")
        if app.scanning:
            raise Denied(409, "a scan is running; apply when it has finished")
        new, _ = apply_decisions(app.require_plan(), body.get('decisions') or {})
        if not new['removals']:
            raise Denied(400, "nothing to apply: accept some groups first")
        user = self.user or f"{self.client_address[0]} (no login)"
        dry_run = bool(body.get('dry_run'))
        jid = app.start_job('apply', lambda: apply_plan(new, mode=mode, move_to=app.move_to, dry_run=dry_run,
                                                        state_dir=app.state_dir, user=user))
        self._json({'job': jid}, 202)

    def post_undo(self, q):
        app = self.app
        journal = self._body().get('journal', '')
        known = {h.get('journal') for h in read_history(app.state_dir) if h.get('op') == 'apply'}
        if journal not in known:
            raise Denied(404, "unknown journal")
        user = self.user or f"{self.client_address[0]} (no login)"
        jid = app.start_job('undo', lambda: undo(journal, state_dir=app.state_dir, user=user))
        self._json({'job': jid}, 202)


def make_server(app: App, host: str, port: int) -> ThreadingHTTPServer:
    handler = type('BoundHandler', (Handler,), {'app': app})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
