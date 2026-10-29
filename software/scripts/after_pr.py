#!/usr/bin/env python3
"""Post-success PR hook. Queue failures without repeating any Git operation."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import uuid

import software as sw

QUEUE = Path.home() / '.team-lark/software-hooks/pending'


@contextmanager
def writer_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def enqueue(queue, url, event, config):
    repo, number = sw.pr_ref(url)
    path = queue / (uuid.uuid4().hex + '.json')
    sw.save(path, {'pr': f'https://github.com/{repo}/pull/{number}', 'event': event,
                   'config': str(Path(config).expanduser().resolve()), 'created_at': sw.now()})
    return path


def drain(queue, config_path, sync=None, limit=5):
    config_path = str(Path(config_path).expanduser().resolve())
    grouped = {}
    for path in sorted(queue.glob('*.json')):
        job = json.loads(path.read_text())
        if job['config'] == config_path:
            sw.pr_ref(job['pr'])
            grouped.setdefault(job['pr'], []).append(path)
    if not grouped:
        return True
    if sync is None:
        config = json.loads(Path(config_path).read_text())
        board = sw.Board(config)
        me = sw.whoami(config)
        sync = lambda url: sw.sync_pr(board, url, me)
    success = True
    for url, paths in list(grouped.items())[:limit]:
        try:
            sync(url)  # Always fetch current GitHub state, never replay a saved state.
        except Exception as exc:
            success = False
            print(f'飞书待补同步：{url}；{exc}', file=sys.stderr)
            continue
        for path in paths:
            path.unlink()  # Delete only the exact jobs successfully processed.
    return success and len(grouped) <= limit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr', help='Verified URL returned by PR creation or lookup')
    parser.add_argument('--event', choices=['created', 'updated', 'merged'], default='updated')
    parser.add_argument('--config', default=str(sw.DEFAULT_CONFIG))
    parser.add_argument('--retry', action='store_true')
    args = parser.parse_args(argv)
    if not args.pr and not args.retry:
        parser.error('--pr or --retry is required')
    try:
        if args.pr:
            enqueue(QUEUE, args.pr, args.event, args.config)
        with writer_lock(QUEUE.parent/'writer.lock'):
            complete = drain(QUEUE, args.config)
        if complete:
            return 0
    except Exception as exc:
        print(f'飞书待补同步：{exc}', file=sys.stderr)
    print('Git 操作结果不受影响；待补记录保留，下次 PR 操作后自动重试。不要重新创建/合并 PR。', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
