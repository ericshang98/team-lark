#!/usr/bin/env python3
"""Reconcile GitHub facts using a Feishu application, with no personal OAuth state."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import software as sw


class FeishuBoard:
    """Legacy Bitable REST adapter; deliberately cannot access the readers table."""
    def __init__(self, config, app_id, app_secret):
        self.c = config
        self.allowed = {config['tables'][key] for key in ('works', 'events')}
        if config['tables'].get('readers') in self.allowed:
            raise ValueError('Readers table must be separate')
        self.token = None
        self.validated = {}
        data = self.request('POST', '/auth/v3/tenant_access_token/internal',
                            {'app_id': app_id, 'app_secret': app_secret}, authenticate=False)
        self.token = data['tenant_access_token']

    def request(self, method, path, payload=None, authenticate=True):
        headers = {'Content-Type': 'application/json; charset=utf-8'}
        if authenticate:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request('https://open.feishu.cn/open-apis' + path,
                    data=sw.dumps(payload).encode() if payload is not None else None,
                    headers=headers, method=method)
        for attempt in range(3 if method == 'GET' else 1):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    result = json.load(response)
                if result.get('code') != 0:
                    # Do not log remote messages or payloads: they can contain record data.
                    raise RuntimeError(f'Feishu API code={result.get("code")}; check application scopes and Base collaborator access')
                return result.get('data', result)
            except (urllib.error.URLError, TimeoutError) as exc:
                retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code in (429, 500, 502, 503, 504)
                if method != 'GET' or not retryable or attempt == 2:
                    raise RuntimeError(f'Feishu transport failure ({getattr(exc, "code", "network")}); writes were not retried') from None
                time.sleep(attempt + 1)

    def path(self, table, suffix=''):
        if table not in self.allowed:
            raise ValueError('Server can only access configured works/events tables')
        base = urllib.parse.quote(self.c['base_token'], safe='')
        return f'/bitable/v1/apps/{base}/tables/{urllib.parse.quote(table, safe="")}' + suffix

    def pages(self, path):
        token = None
        seen = set()
        while True:
            params = {'page_size': 500}
            if token:
                params['page_token'] = token
            data = self.request('GET', path + '?' + urllib.parse.urlencode(params))
            yield from data.get('items', [])
            if not data.get('has_more'):
                return
            token = data.get('page_token')
            if not token or token in seen:
                raise RuntimeError('Feishu pagination stalled')
            seen.add(token)

    @staticmethod
    def row(record):
        fields = {}
        for name, value in record['fields'].items():
            # Legacy REST expands links into display text plus record_ids. Keep
            # the IDs used by the user adapter, not mutable linked titles.
            if isinstance(value, list) and value and all(isinstance(v, dict) and 'record_ids' in v for v in value):
                ids = sorted({rid for v in value for rid in (v['record_ids'] or [])})
                fields[name] = [{'id': rid} for rid in ids] if ids else ''
            else:
                fields[name] = sw.normalized(value)
        return dict(_id=record['record_id'], **fields)

    def list(self, table, fields=None, condition=None):
        if condition:
            raise ValueError('Server does not read user cursors or accept dynamic filters')
        records = [self.row(r) for r in self.pages(self.path(table, '/records'))]
        return records if fields is None else [{k: v for k, v in r.items() if k in fields or k == '_id'} for r in records]

    def get(self, table, rid):
        data = self.request('GET', self.path(table, '/records/' + urllib.parse.quote(rid, safe='')))
        return self.row(data['record'])

    def validate(self, table, fields):
        if table not in self.validated:
            self.validated[table] = {f['field_name'] for f in self.pages(self.path(table, '/fields'))}
        if set(fields) - self.validated[table]:
            raise RuntimeError('Board schema is missing required fields')

    def write(self, table, patch, rid=None):
        self.validate(table, patch)
        suffix = '/records' + ('/' + urllib.parse.quote(rid, safe='') if rid else '')
        self.request('PUT' if rid else 'POST', self.path(table, suffix), {'fields': patch})

    def batch(self, table, records):
        for start in range(0, len(records), 100):
            part = records[start:start+100]
            for row in part:
                self.validate(table, row)
            self.request('POST', self.path(table, '/records/batch_create'),
                         {'records': [{'fields': row} for row in part]})

    def stamp(self, table, rids, patch):
        self.validate(table, patch)
        for start in range(0, len(rids), 100):
            self.request('POST', self.path(table, '/records/batch_update'),
                         {'records': [{'record_id': rid, 'fields': patch} for rid in rids[start:start+100]]})


def validate_config(config, repo):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo) or config.get('repos') != [repo]:
        raise ValueError('Server config must name exactly the current repository')
    tables = config.get('tables', {})
    if not config.get('members') or not all(tables.get(k) for k in ('works', 'events', 'readers')):
        raise ValueError('Missing members or initialized board tables')
    if len(set(tables.values())) != len(tables):
        raise ValueError('Board tables must be separate')


def recovery_since(works):
    # The earliest record survives a partially canceled run; overlap catches delayed discovery.
    dates = [datetime.fromisoformat(r['最近核实UTC']).date() for r in works if r.get('最近核实UTC')]
    baseline = min(dates) if dates else datetime.now(timezone.utc).date() - timedelta(days=7)
    return (baseline - timedelta(days=1)).isoformat()


def reconcile(board, repo):
    validate_config(board.c, repo)
    works = board.list(board.c['tables']['works'])
    tracked = {url for row in works for url in sw.urls(row)}
    if any(sw.pr_ref(url)[0] != repo for url in tracked):
        raise ValueError('Board contains another repository; use separate board/server configuration')
    # Reconcile all tracked PRs + all open + recently changed PRs, not just this event.
    # A superseded Actions run therefore cannot permanently drop a different PR's update.
    snapshot = sw.collect(board.c, recovery_since(works), tracked)
    sw.apply(board, snapshot, None, {'github': 'server', 'open_id': '', 'name': 'GitHub Actions'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify bot read access and schema without writing')
    args = parser.parse_args()
    config = json.loads(os.environ['SOFTWARE_BOARD_CONFIG'])
    repo = os.environ['GITHUB_REPOSITORY']
    validate_config(config, repo)
    board = FeishuBoard(config, os.environ['FEISHU_APP_ID'], os.environ['FEISHU_APP_SECRET'])
    if args.check:
        for key in ('works', 'events'):
            table = config['tables'][key]
            board.validate(table, [f['name'] for f in sw.schema(config)[key][1]])
            board.list(table)
        print('Feishu application read/schema checks passed; write access still requires a real reconciliation.')
        return
    reconcile(board, repo)
    print('Server reconciliation verified; reader cursors and human summaries preserved.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Software board sync failed: {exc}', file=sys.stderr)
        sys.exit(1)
