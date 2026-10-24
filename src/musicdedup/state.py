"""Per-user state: the lock that stops two applies overlapping, and the history
of what has been applied (used by the dashboard's history view)."""

from __future__ import annotations

import contextlib
import json
import os
import time

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None


class Busy(Exception):
    """Another apply or undo is already running."""


def default_state_dir() -> str:
    base = os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'state')
    return os.path.join(base, 'musicdedup')


@contextlib.contextmanager
def apply_lock(state_dir: str):
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, 'apply.lock')
    f = open(path, 'a+')
    try:
        if fcntl is not None:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise Busy("another apply or undo is already running") from e
        yield
    finally:
        f.close()


def record_history(state_dir: str, entry: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, 'history.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps({'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **entry}) + '\n')


def read_history(state_dir: str) -> list[dict]:
    try:
        with open(os.path.join(state_dir, 'history.jsonl'), encoding='utf-8') as f:
            return [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []
