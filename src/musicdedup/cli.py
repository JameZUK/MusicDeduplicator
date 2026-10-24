"""Command-line interface.

    musicdedup scan LIBRARY...              find duplicates, write a plan (changes nothing)
    musicdedup apply PLAN --move-to DIR     move planned files out of the library
    musicdedup apply PLAN --delete          delete planned files
    musicdedup undo JOURNAL                 put moved files back
    musicdedup cache info|clear
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from . import __version__
from .cache import Cache, default_cache_path
from .executor import PlanError, apply_plan, load_plan, undo
from .fingerprint import fpcalc_version
from .pipeline import run_scan
from .planner import Options
from .report import format_report, human_bytes
from .state import default_state_dir

log = logging.getLogger('musicdedup')

FPCALC_HELP = """fpcalc (Chromaprint) is required but was not found on PATH. Install it with:
  Debian/Ubuntu:  sudo apt install libchromaprint-tools
  Fedora:         sudo dnf install chromaprint-tools
  Arch:           sudo pacman -S chromaprint
  macOS:          brew install chromaprint
  Windows:        download fpcalc from https://acoustid.org/chromaprint and put it on PATH"""


def _setup_logging(verbose: int, quiet: bool, log_file: str | None) -> None:
    level = logging.WARNING if quiet else (logging.DEBUG if verbose > 1 else logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(logging.Formatter('%(levelname)s: %(message)s' if verbose else '%(message)s'))
    root.addHandler(console)
    if log_file:
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        root.addHandler(fh)


def _confirm(prompt: str, expected: str) -> bool:
    if not sys.stdin.isatty():
        log.error("Refusing to continue without confirmation: not running interactively. Use --yes.")
        return False
    try:
        return input(prompt).strip().lower() == expected
    except EOFError:
        return False


def _open_cache(args) -> Cache:
    return Cache(None if args.no_cache else (args.cache or default_cache_path()))


def cmd_scan(args) -> int:
    version = fpcalc_version()
    if not version:
        log.error(FPCALC_HELP)
        return 1
    for p in args.library:
        if not os.path.isdir(p):
            log.error("Not a folder: %s", p)
            return 2
    for p in args.prefer:
        if not os.path.isdir(p):
            log.error("--prefer folder does not exist: %s", p)
            return 2
    log.debug("Using %s", version)
    progress = not args.quiet and sys.stderr.isatty()
    plan_path = os.path.abspath(args.plan)
    plan = run_scan(args.library, plan_path=plan_path,
                    cache_path=None if args.no_cache else (args.cache or default_cache_path()),
                    options=Options(prefer=args.prefer, within_folders=args.within_folders,
                                    remove_smaller_editions=args.remove_smaller_editions),
                    excludes=args.exclude, workers=args.workers, progress=progress,
                    state_dir=default_state_dir())
    print(format_report(plan, limit=None if args.full_report else 25))
    print(f"\nPlan written to {plan_path}")
    if plan['removals']:
        print("Nothing has been changed. To act on it, review the plan, then run:\n"
              f"  musicdedup apply {args.plan} --move-to /path/outside/library    (reversible)\n"
              f"  musicdedup apply {args.plan} --delete                            (permanent)")
    return 0


def cmd_apply(args) -> int:
    plan = load_plan(args.plan)
    s = plan['summary']
    n, size = s['files_to_remove'], human_bytes(s['bytes_to_free'])
    if not plan['removals']:
        print("The plan has nothing to remove.")
        return 0
    if args.delete:
        mode, what = 'delete', f"permanently DELETE {n} files ({size})"
    else:
        mode, what = 'move', f"move {n} files ({size}) to {args.move_to}"
    if not args.dry_run and not args.yes:
        print(f"This will {what}. Each file is re-checked first; changed files are skipped.")
        expected = 'delete' if args.delete else 'y'
        if not _confirm("Type 'delete' to confirm: " if args.delete else "Continue? [y/N] ", expected):
            print("Cancelled; nothing was changed.")
            return 1
    result = apply_plan(plan, mode=mode, move_to=args.move_to, dry_run=args.dry_run,
                        journal_path=args.journal, state_dir=default_state_dir(), user=getpass.getuser())
    done = ', '.join(f"{v} {k}" for k, v in sorted(result.counts.items())) or 'nothing done'
    prefix = '[dry run] ' if args.dry_run else ''
    print(f"\n{prefix}{done}; {human_bytes(result.bytes_freed)} {'would be ' if args.dry_run else ''}freed.")
    if result.skipped:
        print(f"{len(result.skipped)} files were skipped:")
        for path, why in result.skipped[:20]:
            print(f"  {path}: {why}")
    if result.journal:
        print(f"Journal: {result.journal}")
        if mode == 'move':
            print(f"To put everything back: musicdedup undo '{result.journal}'")
    return 0 if not result.counts.get('failed') else 1


def cmd_undo(args) -> int:
    result = undo(args.journal, dry_run=args.dry_run, state_dir=default_state_dir(), user=getpass.getuser())
    done = ', '.join(f"{v} {k}" for k, v in sorted(result.counts.items())) or 'nothing to do'
    print(('[dry run] ' if args.dry_run else '') + done)
    for path, why in result.skipped[:20]:
        print(f"  {path}: {why}")
    return 0 if not result.counts.get('failed') else 1


def cmd_serve(args) -> int:
    from .web.access import DEFAULT_ALLOW, AccessPolicy
    from .web.server import App, make_server
    try:
        policy = AccessPolicy(mode=args.auth, allow=args.allow or DEFAULT_ALLOW,
                              trusted_proxies=args.trusted_proxy, hostnames=args.hostname)
    except ValueError as e:
        log.error("%s", e)
        return 2
    if args.move_to and not os.path.isdir(args.move_to):
        log.error("--move-to folder does not exist: %s", args.move_to)
        return 2
    for p in args.library:
        if not os.path.isdir(p):
            log.error("--library folder does not exist: %s", p)
            return 2
    if args.scan_on_start and not args.library:
        log.error("--scan-on-start needs --library")
        return 2
    app = App(args.plan, policy, state_dir=default_state_dir(), cache_path=args.cache or default_cache_path(),
              move_to=args.move_to, allow_delete=args.allow_delete, library=args.library,
              excludes=args.exclude, workers=args.workers,
              scan_options=Options(prefer=args.prefer, within_folders=args.within_folders,
                                   remove_smaller_editions=args.remove_smaller_editions))
    server = make_server(app, args.host, args.port)
    if args.scan_on_start:
        app.start_scan('server start')
    where = ', '.join(policy.allow) if args.auth == 'none' else f"login via proxy {', '.join(args.trusted_proxy)}"
    print(f"Dashboard on http://{args.host}:{args.port}/  (access: {where})")
    if args.host in ('127.0.0.1', 'localhost', '::1'):
        print("Only this machine can connect. Use --host 0.0.0.0 to allow your LAN.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_cache(args) -> int:
    cache = Cache(args.cache or default_cache_path())
    try:
        if args.action == 'clear':
            cache.clear()
            print(f"Cleared {cache.path}")
        else:
            st = cache.stats()
            print(f"{st['path']}: {st['entries']} files ({st['errors']} unreadable), {human_bytes(st['bytes'])}")
    finally:
        cache.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('-v', '--verbose', action='count', default=0, help="more detail (-vv for debug)")
    common.add_argument('-q', '--quiet', action='store_true', help="only warnings and errors")
    common.add_argument('--log-file', help="also write a detailed log to this file")

    p = argparse.ArgumentParser(prog='musicdedup', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', action='version', version=f'musicdedup {__version__}')
    sub = p.add_subparsers(dest='command', required=True)

    s = sub.add_parser('scan', parents=[common], help="find duplicates and write a plan (changes nothing)")
    s.add_argument('library', nargs='+', help="music folder(s) to scan")
    s.add_argument('-o', '--plan', default='musicdedup-plan.json', help="where to write the plan")
    s.add_argument('--prefer', action='append', default=[], metavar='FOLDER',
                   help="when copies are equally good, keep the one under this folder (repeatable)")
    s.add_argument('--within-folders', action='store_true',
                   help="also remove duplicate copies of a track inside the same folder")
    s.add_argument('--remove-smaller-editions', action='store_true',
                   help="also remove an edition whose tracks are all in a bigger one "
                        "(e.g. the standard album when you have the deluxe)")
    s.add_argument('--exclude', action='append', default=[], metavar='PATTERN',
                   help="skip folders matching this name or relative-path pattern (repeatable)")
    s.add_argument('--workers', type=int, help="parallel fingerprinting jobs (default: CPU count)")
    s.add_argument('--cache', help=f"fingerprint cache file (default: {default_cache_path()})")
    s.add_argument('--no-cache', action='store_true', help="don't read or write the cache")
    s.add_argument('--full-report', action='store_true', help="print every entry, not just the first 25")
    s.set_defaults(func=cmd_scan)

    a = sub.add_parser('apply', parents=[common], help="move or delete the files in a plan")
    a.add_argument('plan', help="plan file written by 'scan'")
    how = a.add_mutually_exclusive_group(required=True)
    how.add_argument('--move-to', metavar='DIR', help="move files here (outside the library); reversible")
    how.add_argument('--delete', action='store_true', help="delete files permanently")
    a.add_argument('-n', '--dry-run', action='store_true', help="show what would happen; change nothing")
    a.add_argument('-y', '--yes', action='store_true', help="don't ask for confirmation")
    a.add_argument('--journal', help="where to write the journal of actions")
    a.set_defaults(func=cmd_apply)

    u = sub.add_parser('undo', parents=[common], help="put moved files back, using a journal")
    u.add_argument('journal')
    u.add_argument('-n', '--dry-run', action='store_true')
    u.set_defaults(func=cmd_undo)

    w = sub.add_parser('serve', parents=[common], help="open the review dashboard for a plan")
    w.add_argument('plan', help="plan file written by 'scan'")
    w.add_argument('--host', default='127.0.0.1', help="address to listen on (default: 127.0.0.1)")
    w.add_argument('--port', type=int, default=8650)
    w.add_argument('--auth', choices=['none', 'authelia'], default='none',
                   help="none: no login, LAN addresses only; authelia: trust a login proxy")
    w.add_argument('--allow', action='append', metavar='CIDR',
                   help="with --auth none, addresses allowed in (repeatable; default: loopback and private LAN ranges)")
    w.add_argument('--trusted-proxy', action='append', default=[], metavar='CIDR',
                   help="with --auth authelia, the reverse proxy's address (repeatable)")
    w.add_argument('--hostname', action='append', default=[], metavar='NAME',
                   help="extra host name the dashboard is reached by (repeatable)")
    w.add_argument('--move-to', metavar='DIR', help="quarantine folder for moves made from the dashboard")
    w.add_argument('--allow-delete', action='store_true', help="allow permanent deletes from the dashboard")
    w.add_argument('--cache', help="fingerprint cache file")
    w.add_argument('--library', action='append', default=[], metavar='FOLDER',
                   help="music folder(s) to rescan from the dashboard (repeatable); the plan is written to PLAN")
    w.add_argument('--exclude', action='append', default=[], metavar='PATTERN', help="as for scan")
    w.add_argument('--prefer', action='append', default=[], metavar='FOLDER', help="as for scan")
    w.add_argument('--within-folders', action='store_true', help="as for scan")
    w.add_argument('--remove-smaller-editions', action='store_true', help="as for scan")
    w.add_argument('--workers', type=int, help="parallel fingerprinting jobs for rescans")
    w.add_argument('--scan-on-start', action='store_true', help="start a rescan as soon as the server starts")
    w.set_defaults(func=cmd_serve)

    c = sub.add_parser('cache', parents=[common], help="show or clear the fingerprint cache")
    c.add_argument('action', choices=['info', 'clear'])
    c.add_argument('--cache', help="cache file")
    c.set_defaults(func=cmd_cache)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose, args.quiet, args.log_file)
    try:
        return args.func(args)
    except PlanError as e:
        log.error("%s", e)
        return 1
    except KeyboardInterrupt:
        log.error("Interrupted. Fingerprints done so far are cached; any journal is up to date.")
        return 130
