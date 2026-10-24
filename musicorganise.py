#!/usr/bin/env python3
"""Compatibility wrapper for the old command line. Use `musicdedup` instead.

    python3 musicorganise.py -p LIBRARY -a list
    python3 musicorganise.py -p LIBRARY -a move -m DIR [--dry-run]
    python3 musicorganise.py -p LIBRARY -a delete [--dry-run] [-y]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from musicdedup.cli import main as musicdedup_main  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Old interface to musicdedup (deprecated).")
    p.add_argument('-p', '--path', required=True)
    p.add_argument('-a', '--action', required=True, choices=['list', 'move', 'delete'])
    p.add_argument('-m', '--move-dir')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('-y', '--yes', action='store_true')
    p.add_argument('--clear-cache', action='store_true')
    p.add_argument('--log-level', help=argparse.SUPPRESS)
    p.add_argument('--no-multiprocessing', action='store_true', help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.action == 'move' and not args.move_dir:
        p.error("--move-dir is required when action is 'move'")

    print("Note: musicorganise.py is deprecated; see README.md for the `musicdedup` command.\n",
          file=sys.stderr)
    if args.clear_cache:
        musicdedup_main(['cache', 'clear'])
    plan = 'musicdedup-plan.json'
    flags = ['-v'] if args.verbose else []
    status = musicdedup_main(['scan', args.path, '--plan', plan, *flags])
    if status or args.action == 'list':
        return status
    apply = ['apply', plan, *flags]
    apply += ['--move-to', args.move_dir] if args.action == 'move' else ['--delete']
    if args.dry_run:
        apply.append('--dry-run')
    if args.yes:
        apply.append('--yes')
    return musicdedup_main(apply)


if __name__ == '__main__':
    sys.exit(main())
