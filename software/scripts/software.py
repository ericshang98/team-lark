#!/usr/bin/env python3
"""One-shot software coordination. Python stdlib + authenticated gh/lark-cli."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta

DEFAULT_CONFIG = Path.home() / '.team-lark/software.json'
STATES = ['开发中', '待评审', '待合并', '部分合并', '已合并', '已关闭']
HUMAN = ['工作内容', '负责人', 'GitHub作者', '涉及模块', '工作摘要', '协调事项', '验证与交付', '关联任务', '分支', 'PR链接']
MACHINE = ['开发状态', 'PR事实', '检查与评审', '事实摘要']
CONTENT = HUMAN + MACHINE


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def save(path, obj):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(dumps(obj) + '\n')
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def run_once(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
    p = subprocess.run(args, capture_output=True, text=True, env=env, timeout=180)
    if p.returncode:
        # Never echo full argv: it may contain private record content.
        raise RuntimeError(f'{args[0]} {args[1]} failed: {(p.stderr or p.stdout)[:1200]}')
    data = json.loads(p.stdout)
    if isinstance(data, dict) and data.get('ok') is False:
        raise RuntimeError(str(data.get('error')))
    return data


def run(args):
    # Retry only read operations, never an ambiguous mutation.
    readonly = (args[0] == 'gh' and (args[1:3] in [['pr', 'list'], ['pr', 'view']] or args[1:3] == ['api', 'user'])) or (args[0] == 'lark-cli' and (args[1] == 'whoami' or args[2] in {'+record-list', '+record-get', '+field-list', '+table-list'}))
    for attempt in range(3 if readonly else 1):
        try:
            return run_once(args)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            transient = any(word in str(exc).lower() for word in ['timeout', 'timed out', '502', '503', '504', 'bad gateway', 'tls handshake', 'connection reset'])
            if not readonly or not transient or attempt == 2:
                raise
            time.sleep(attempt + 1)


def confirmed_read(read, matches, error):
    # Read-your-write may lag. Never retry the mutation to fix a stale read.
    for attempt in range(4):
        value = read()
        if matches(value):
            return value
        if attempt < 3:
            time.sleep(attempt + 1)
    raise RuntimeError(error)


def normalized(value):
    if value is None:
        return ''
    if isinstance(value, list):
        if all(isinstance(v, dict) and 'id' in v for v in value):
            return sorted([{'id': v['id']} for v in value], key=lambda v: v['id'])
        if all(isinstance(v, dict) and 'text' in v for v in value):
            return ''.join(v['text'] for v in value)
    return value


def rows(payload):
    fields, ids, values = payload['fields'], payload['record_id_list'], payload['data']
    if len(ids) != len(values):
        raise RuntimeError('Lark record IDs/rows do not align')
    return [dict(_id=ids[i], **{k: (v[0] if k == '开发状态' and isinstance(v, list) and len(v) == 1 else normalized(v)) for k, v in (zip(fields, row) if isinstance(row, list) else row.items())})
            for i, row in enumerate(values)]


def index_unique(records, key):
    out = {}
    for row in records:
        value = row.get(key)
        if not value:
            raise RuntimeError(f'Missing business key: {key}')
        if value in out:
            raise RuntimeError(f'Duplicate {key}: {value}; reconcile duplicates before writing')
        out[value] = row
    return out


class Board:
    def __init__(self, config):
        self.c = config
        self.validated = set()

    def call(self, command, *args):
        result = run(['lark-cli', 'base', command, '--as', 'user', '--base-token', self.c['base_token'], *args])
        if result.get('ok') is not True:
            raise RuntimeError('Lark returned no confirmed success')
        data = result['data']
        if data.get('ignored_fields'):
            raise RuntimeError('Lark ignored fields; write is not verified')
        return data

    def validate(self, table):
        if table not in self.validated:
            actual = self.call('+field-list', '--table-id', table)
            self.validated.add(table)
            return actual

    def list(self, table, fields=None, condition=None):
        offset, result = 0, []
        while True:
            args = ['--table-id', table, '--format', 'json', '--limit', '200', '--offset', str(offset)]
            for name in fields or []:
                args += ['--field-id', name]
            if condition:
                args += ['--filter-json', dumps(condition)]
            page = self.call('+record-list', *args)
            batch = rows(page)
            result += batch
            if page.get('has_more') is False or len(batch) < 200 and not page.get('has_more'):
                break
            if not batch:
                raise RuntimeError('Pagination stalled')
            offset += len(batch)
        return result

    def get(self, table, rid):
        data = self.call('+record-get', '--table-id', table, '--record-id', rid, '--format', 'json')
        result = rows(data)
        if len(result) != 1:
            raise RuntimeError(f'Record disappeared: {rid}')
        return result[0]

    def write(self, table, patch, rid=None):
        self.validate(table)
        args = ['--table-id', table, '--json', dumps(patch)]
        if rid:
            args += ['--record-id', rid]
        self.call('+record-upsert', *args)
        # Lookup also resolves an ambiguous create without blindly replaying it.

    def stamp(self, table, rids, patch):
        self.validate(table)
        for start in range(0, len(rids), 200):
            self.call('+record-batch-update', '--table-id', table, '--json', dumps({
                'record_id_list': rids[start:start+200], 'patch': patch}))

    def batch(self, table, records):
        if not records:
            return
        self.validate(table)
        fields = list(dict.fromkeys(k for row in records for k in row))
        for start in range(0, len(records), 100):
            part = records[start:start + 100]
            self.call('+record-batch-create', '--table-id', table, '--json', dumps({
                'fields': fields, 'rows': [[row.get(k) for k in fields] for row in part]}))


def schema(config):
    def text(name):
        return {'name': name, 'type': 'text'}
    works = [text('工作内容'), text('工作ID'), {'name': '负责人', 'type': 'user'}, text('GitHub作者'),
             text('涉及模块'), text('工作摘要'),
             {'name': '开发状态', 'type': 'select', 'options': [{'name': s} for s in STATES]},
             text('协调事项'), text('验证与交付'), text('分支'), text('PR链接'), text('事实摘要'),
             text('检查与评审'), text('最近核实UTC'), text('核实情况'), text('PR事实'),
             text('变化ID'), text('变化摘要'), text('内容摘要'), text('变化时间UTC')]
    if config.get('task_table'):
        works.append({'name': '关联任务', 'type': 'link', 'link_table': config['task_table']})
    return {
        'works': ('软件协作', works),
        'events': ('软件动态', [text(n) for n in ['变化摘要', '变化ID', '工作ID', '工作内容', '发生时间UTC', '快照']]),
        'readers': ('软件阅读记录', [text(n) for n in ['阅读者', 'open_id', '已读版本', '阅读时间UTC']]),
    }


def setup(board, path):
    # Check names first so an interrupted setup reuses prior successful tables.
    existing = board.call('+table-list', '--limit', '100')['tables']
    if len(existing) >= 100:
        raise RuntimeError('Table directory exceeds setup limit; configure table IDs explicitly')
    config = board.c
    config.setdefault('tables', {})
    for key, (name, fields) in schema(config).items():
        matches = [t for t in existing if t['name'] == name]
        if len(matches) > 1:
            raise RuntimeError(f'Ambiguous table: {name}')
        if key not in config['tables']:
            if matches:
                config['tables'][key] = matches[0]['id']
            else:
                created = board.call('+table-create', '--name', name, '--fields', dumps(fields))
                table = created.get('table', created)
                config['tables'][key] = table.get('id') or table.get('table_id')
                if not config['tables'][key]:
                    raise RuntimeError(f'Unknown table-create result: {created}')
            save(path, config)
        actual = board.validate(config['tables'][key])
        names = {f['name'] for f in actual['fields']}
        missing = {f['name'] for f in fields} - names
        if missing:
            raise RuntimeError(f'{name} missing fields {missing}; inspect before schema migration')
    print(dumps(config))


def whoami(config, verify_github=True):
    me = run(['lark-cli', 'whoami', '--json']).get('onBehalfOf', {})
    oid = me.get('openId')
    if not oid:
        raise RuntimeError('No signed-in Lark user')
    members = config.get('members', {})
    login = next((k for k, v in members.items() if v['open_id'] == oid), None)
    if not login:
        raise RuntimeError('Current user has no verified GitHub/Lark mapping in software.json')
    if verify_github:
        github = run(['gh', 'api', 'user'])['login']
        if github.lower() != login.lower():
            raise RuntimeError('GitHub and Lark identities do not match configured member')
    return {'open_id': oid, 'name': me.get('userName', login), 'github': login}


PR_FIELDS = 'number,title,state,isDraft,author,url,headRefName,baseRefName,headRefOid,updatedAt,mergedAt,reviewDecision,mergeable,statusCheckRollup,files,body'


def pr_ref(url):
    m = re.fullmatch(r'https://github.com/([\w.-]+/[\w.-]+)/pull/(\d+)', url.strip())
    if not m:
        raise ValueError(f'Invalid GitHub PR URL: {url}')
    return m.group(1), int(m.group(2))


def fetch_pr(url):
    repo, number = pr_ref(url)
    result = run(['gh', 'pr', 'view', str(number), '--repo', repo, '--json', PR_FIELDS])
    result['checksCollected'] = True
    return result


def collect(config, since, tracked):
    discovered = {}
    for repo in config['repos']:
        for state, search in [('open', ''), ('all', f'updated:>={since}')]:
            args = ['gh', 'pr', 'list', '--repo', repo, '--state', state, '--limit', '1000',
                    '--json', 'number,title,state,isDraft,author,url,headRefName,baseRefName,headRefOid,updatedAt,mergedAt,body']
            if search:
                args += ['--search', search]
            result = run(args)
            if len(result) >= 1000:
                raise RuntimeError('PR discovery hit 1000-result limit; narrow the time range')
            for pr in result:
                pr['checksCollected'] = False
                discovered[pr['url']] = pr
    missing = (set(tracked) - discovered.keys()) | {u for u,p in discovered.items() if p['state'] == 'OPEN'}
    for url in missing:
        repo, _ = pr_ref(url)
        if repo not in config['repos']:
            raise RuntimeError(f'Unconfigured repository in board: {repo}')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for pr in pool.map(fetch_pr, sorted(missing)):
            discovered[pr['url']] = pr
    return {'collected_at': now(), 'since': since, 'repos': config['repos'], 'prs': list(discovered.values())}


def checks(pr):
    rollup = pr.get('statusCheckRollup') or []
    status = []
    for check in rollup:
        value = check.get('conclusion') or check.get('state') or check.get('status') or 'UNKNOWN'
        status.append({'name': check.get('name') or check.get('context') or 'check', 'result': value,
                       'url': check.get('detailsUrl') or check.get('targetUrl') or ''})
    return sorted(status, key=lambda c: (c['name'], c['url']))


def facts(prs):
    return sorted([{'url': p['url'], 'number': p['number'], 'title': p['title'], 'state': p['state'],
                    'draft': p['isDraft'], 'head': p['headRefOid'], 'branch': p['headRefName'],
                    'base': p['baseRefName'], 'review': p.get('reviewDecision') or 'UNKNOWN',
                    'mergeable': p.get('mergeable') or 'UNKNOWN', 'checksCollected': p.get('checksCollected', True), 'checks': checks(p)} for p in prs], key=lambda p: p['url'])


def stage(prs):
    if not prs:
        return '开发中'
    if all(p['state'] == 'MERGED' for p in prs):
        return '已合并'
    if all(p['state'] == 'CLOSED' for p in prs):
        return '已关闭'
    if any(p['state'] == 'MERGED' for p in prs):
        return '部分合并'
    opened = [p for p in prs if p['state'] == 'OPEN']
    if any(p['isDraft'] for p in opened):
        return '开发中'
    if opened and all(p.get('reviewDecision') == 'APPROVED' for p in opened):
        return '待合并'
    return '待评审'


def machine_patch(prs):
    fs = facts(prs)
    state_counts = {state: sum(p['state'] == state for p in prs) for state in ['OPEN', 'MERGED', 'CLOSED']}
    details = []
    for p in fs:
        failed = [c['name'] for c in p['checks'] if c['result'] in {'FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED'}]
        pending = [c['name'] for c in p['checks'] if c['result'] not in {'SUCCESS', 'NEUTRAL', 'SKIPPED', 'FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED'}]
        details.append(f"#{p['number']} {p['state']} / {'Draft / ' if p['draft'] else ''}review={p['review']} / mergeable={p['mergeable']} / "
                       + (f"失败: {', '.join(failed)}" if failed else f"进行中: {', '.join(pending)}" if pending else '已返回检查通过/跳过' if p['checks'] else '无检查记录' if p['checksCollected'] else '未采集已关闭 PR 的历史检查'))
    return {'开发状态': stage(prs), 'PR事实': dumps(fs), '检查与评审': '\n'.join(details),
            '事实摘要': f"{len(prs)} PR：{state_counts['OPEN']} 未合并，{state_counts['MERGED']} 已合并，{state_counts['CLOSED']} 已关闭；安装/上线另行验证。" if prs else '本地进行中，尚无 PR 证据。'}


def urls(row):
    return [u.strip() for u in (row.get('PR链接') or '').splitlines() if u.strip()]


def fingerprint(row):
    return hashlib.sha256(dumps({k: normalized(row.get(k)) for k in CONTENT}).encode()).hexdigest()


def revision(old, new):
    if old and old.get('内容摘要') == fingerprint(new):
        return {}
    changed = [k for k in CONTENT if normalized((old or {}).get(k)) != normalized(new.get(k))]
    summary = '首次登记' if not old else '更新：' + '、'.join('PR提交/内容' if k == 'PR事实' else k for k in changed)
    return {'变化ID': uuid.uuid4().hex, '变化摘要': summary, '变化时间UTC': now(), '内容摘要': fingerprint(new)}


def event(row):
    return {'变化ID': row['变化ID'], '工作ID': row['工作ID'], '工作内容': row['工作内容'],
            '变化摘要': row['变化摘要'], '发生时间UTC': row['变化时间UTC'],
            '快照': dumps({k: row.get(k) for k in CONTENT})}


def reconcile_events(board, works):
    table = board.c['tables']['events']
    known = index_unique(board.list(table, ['变化ID']), '变化ID')
    missing = [event(row) for row in works if row.get('变化ID') and row['变化ID'] not in known]
    board.batch(table, missing)
    if missing:
        confirmed_read(lambda: index_unique(board.list(table, ['变化ID']), '变化ID'),
                       lambda current: all(e['变化ID'] in current for e in missing),
                       'Event write not verified; do not replay the write blindly')


def human_patch(item, config, me, import_history):
    owner = item.get('owner', me['github'])
    if owner not in config['members']:
        raise RuntimeError(f'Unknown member: {owner}')
    if owner != me['github'] and not import_history:
        raise RuntimeError('Cannot edit another member\'s summary; --import-history requires explicit user request')
    out = {'工作ID': item['key'], '负责人': [{'id': config['members'][owner]['open_id']}], 'GitHub作者': owner}
    mapping = {'title': '工作内容', 'module': '涉及模块', 'summary': '工作摘要', 'coordination': '协调事项',
               'validation': '验证与交付', 'branch': '分支'}
    for k, dest in mapping.items():
        if k in item:
            out[dest] = item[k]
    if 'prs' in item:
        for url in item['prs']:
            pr_ref(url)
        out['PR链接'] = '\n'.join(sorted(set(item['prs'])))
    if 'tasks' in item:
        out['关联任务'] = [{'id': rid} for rid in item['tasks']]
    return out


def apply(board, snapshot, plan, me, import_history=False, dry_run=False, work_ids=None):
    table = board.c['tables']['works']
    old_rows = board.list(table)
    index_unique(old_rows, '工作ID')
    if work_ids is not None:
        wanted = {p['url'] for p in snapshot['prs']}
        if any(wanted.intersection(urls(r)) for r in old_rows if r['工作ID'] not in work_ids):
            raise RuntimeError('PR grouping changed during targeted sync; reread before writing')
        old_rows = [r for r in old_rows if r['工作ID'] in work_ids]
    old = index_unique(old_rows, '工作ID')
    prs = {p['url']: p for p in snapshot['prs']}
    # Validate the entire plan and PR ownership before any mutation.
    patches = {}
    for item in (plan or {}).get('works', []):
        if item['key'] in patches:
            raise RuntimeError('Duplicate work key in plan')
        patch = human_patch(item, board.c, me, import_history)
        before = old.get(item['key'])
        if before and before.get('GitHub作者') != me['github'] and not import_history:
            raise RuntimeError('Cannot overwrite another member\'s work')
        patches[item['key']] = patch
    combined = {k: dict(v) for k, v in old.items()}
    for key, patch in patches.items():
        combined[key] = dict(combined.get(key, {}), **patch)
    claimed = {}
    for key, row in combined.items():
        for url in urls(row):
            if url in claimed:
                raise RuntimeError(f'PR belongs to multiple works: {url}')
            claimed[url] = key
            if url not in prs:
                raise RuntimeError(f'PR not verified this run: {url}')
    # Previously unknown PRs get provisional individual rows, never guessed thematic grouping.
    for url, p in prs.items():
        if url in claimed or p['author']['login'] not in board.c['members']:
            continue
        repo, num = pr_ref(url)
        key = f'{repo}#{num}'
        if key in combined:
            raise RuntimeError('Provisional work key collision')
        owner = p['author']['login']
        combined[key] = {'工作ID': key, '工作内容': p['title'], 'GitHub作者': owner,
                         '负责人': [{'id': board.c['members'][owner]['open_id']}],
                         'PR链接': url, '分支': p['headRefName'], '工作摘要': '按 PR 自动登记；待负责人补充工作背景。',
                         '验证与交付': '安装与上线未核实。'}
    updates, creates = [], []
    for key, row in combined.items():
        patch = dict(patches.get(key, {}))
        verified = [prs[u] for u in urls(row)]
        patch.update(machine_patch(verified))
        after = dict(row, **patch)
        change = revision(old.get(key), after)
        patch.update(change)
        patch.update({'最近核实UTC': snapshot['collected_at'], '核实情况': '已核实 GitHub' if verified else '本地工作自报'})
        if key not in old:
            creates.append(dict(after, **patch))
        else:
            patch = {k: v for k, v in patch.items() if normalized(old[key].get(k)) != normalized(v)}
            if patch:
                updates.append((old[key], patch))
    if dry_run:
        print(dumps({'create': len(creates), 'change': sum('变化ID' in p for _, p in updates),
                     'works': [{k: r.get(k) for k in ['工作ID','工作内容','GitHub作者','开发状态','事实摘要']} for r in creates]}))
        return
    reconcile_events(board, old_rows)  # Recover prior writes before replacing any latest revision.
    stamp_groups = {}
    for before, patch in updates:
        if set(patch) <= {'最近核实UTC', '核实情况'}:
            stamp_groups.setdefault(dumps(patch), []).append(before['_id'])
            continue
        current = board.get(table, before['_id'])
        if fingerprint(current) != fingerprint(before) or current.get('变化ID') != before.get('变化ID'):
            raise RuntimeError('Board changed during sync; stopped before overwriting. Rerun from fresh data.')
        # Only write owned human fields and machine projection, never whole stale records.
        board.write(table, patch, before['_id'])
    for encoded, rids in stamp_groups.items():
        board.stamp(table, rids, json.loads(encoded))
    if creates:
        fresh = index_unique(board.list(table, ['工作ID']), '工作ID')
        if any(r['工作ID'] in fresh for r in creates):
            raise RuntimeError('Concurrent work creation detected; rerun from fresh data')
        board.batch(table, creates)
    expected = [(r['工作ID'], r) for r in creates] + [(r['工作ID'], p) for r, p in updates]
    def verified(records):
        indexed = index_unique(records, '工作ID')
        return all(key in indexed and all(normalized(indexed[key].get(k)) == normalized(v)
                   for k, v in patch.items() if k != '_id') for key, patch in expected)
    result = confirmed_read(lambda: board.list(table), verified, 'Write verification failed; stop and inspect')
    reconcile_events(board, [r for r in result if work_ids is None or r['工作ID'] in work_ids])
    print(f'已核实 {len(prs)} PR；新增 {len(creates)} 项工作；{sum("变化ID" in p for _, p in updates)} 项实质变化。')


def sync_pr(board, url, me):
    """Refresh one work and all its linked PRs; never consume a reading receipt."""
    repo, number = pr_ref(url)
    if repo not in board.c['repos']:
        raise RuntimeError(f'Repository is not configured for this board: {repo}')
    url = f'https://github.com/{repo}/pull/{number}'
    works = board.list(board.c['tables']['works'])
    index_unique(works, '工作ID')
    matches = [r for r in works if url in urls(r)]
    if len(matches) > 1:
        raise RuntimeError('PR belongs to multiple works; resolve grouping first')
    key = matches[0]['工作ID'] if matches else f'{repo}#{number}'
    targets = urls(matches[0]) if matches else [url]
    if any(pr_ref(target)[0] not in board.c['repos'] for target in targets):
        raise RuntimeError('Linked work contains an unconfigured repository')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        prs = list(pool.map(fetch_pr, targets))
    current = next(p for p in prs if p['url'] == url)
    if current['author']['login'] not in board.c['members']:
        raise RuntimeError('PR author has no verified team member mapping')
    plan = None
    if not matches and current['author']['login'] == me['github']:
        # A concise evidence-based default. Never replace an existing human summary.
        plan = {'works': [{'key': key, 'owner': me['github'], 'title': current['title'],
                           'summary': current['title'], 'branch': current['headRefName'],
                           'prs': [url], 'validation': '安装与上线未核实；测试见 PR 说明及检查。'}]}
    apply(board, {'prs': prs, 'collected_at': now()}, plan, me, work_ids={key})
    print(f'软件看板已同步：{url} → {current["state"]}；未改变阅读记录。')


def report(board, me, path):
    works = board.list(board.c['tables']['works'])
    index_unique(works, '工作ID')
    readers = board.list(board.c['tables']['readers'], condition={'logic':'and','conditions':[['open_id','==',me['open_id']]]})
    if len(readers) > 1:
        raise RuntimeError('Duplicate reader cursor')
    seen = json.loads(readers[0].get('已读版本') or '{}') if readers else {}
    unread = [r for r in works if seen.get(r['工作ID']) != r.get('变化ID')]
    unread.sort(key=lambda r: (r.get('开发状态') in ['已合并','已关闭'], r.get('GitHub作者') == me['github'], r['工作内容']))
    lines = [f"软件协作 · {me['name']} · {now()}", f'自上次查看：{len(unread)} 项工作有变化。首次运行展示当前全部工作。']
    for r in unread:
        lines += [f"\n- {r['工作内容']}｜{r.get('GitHub作者')}｜{r.get('开发状态')}",
                  '  ' + (r.get('工作摘要') or ''), '  ' + (r.get('事实摘要') or ''),
                  '  ' + (r.get('变化摘要') or '')]
        if r.get('协调事项'):
            lines.append('  协调：' + r['协调事项'])
        if r.get('验证与交付'):
            lines.append('  验证与交付：' + r['验证与交付'])
        lines.append('  ' + ' '.join(urls(r)))
    active = [r for r in works if r.get('开发状态') not in ['已合并','已关闭']]
    lines.append('\n当前未完成工作：')
    for r in active:
        lines.append(f"- {r['工作内容']}：{r.get('检查与评审') or '暂无 PR'}；核实于 {r.get('最近核实UTC') or '未知'}")
    lines.append('\n模块重叠提醒（只表示可能需要协调，不等于代码冲突）：')
    overlaps = []
    for i, a in enumerate(active):
        for b in active[i+1:]:
            modules = set((a.get('涉及模块') or '').split(',')) & set((b.get('涉及模块') or '').split(',')) - {''}
            if modules and a.get('GitHub作者') != b.get('GitHub作者'):
                overlaps.append(f"- {a['工作内容']} ↔ {b['工作内容']}：{', '.join(sorted(modules))}")
    lines += overlaps or ['- 无已登记的跨负责人模块重叠；未登记工作不在覆盖范围。']
    receipt = {'base_token': board.c['base_token'], 'table': board.c['tables']['works'], 'open_id': me['open_id'],
               'versions': {r['工作ID']:r['变化ID'] for r in unread if r.get('变化ID')}, 'generated_at':now()}
    save(path, receipt)
    output = '\n'.join(lines)
    Path(str(path) + '.md').write_text(output + '\n')
    print(output)
    print(f'\n阅读回执：{path}（展示给用户后再 ack；本命令未推进阅读记录）')


def ack(board, me, path):
    receipt = json.loads(Path(path).read_text())
    if any(receipt.get(k) != v for k,v in {'base_token':board.c['base_token'], 'table':board.c['tables']['works'], 'open_id':me['open_id']}.items()):
        raise RuntimeError('Receipt belongs to another reader/board')
    records = board.list(board.c['tables']['readers'], condition={'logic':'and','conditions':[['open_id','==',me['open_id']]]})
    if len(records) > 1:
        raise RuntimeError('Duplicate reader record')
    old = records[0] if records else {}
    if old.get('阅读时间UTC', '') > receipt['generated_at']:
        raise RuntimeError('Stale receipt cannot rewind a newer reading cursor')
    seen = json.loads(old.get('已读版本') or '{}')
    seen.update(receipt['versions'])  # Only acknowledge versions actually included in this report.
    patch = {'阅读者': me['name'], 'open_id': me['open_id'], '已读版本':dumps(seen), '阅读时间UTC':receipt['generated_at']}
    board.write(board.c['tables']['readers'], patch, old.get('_id'))
    confirmed_read(lambda: board.list(board.c['tables']['readers'], condition={'logic':'and','conditions':[['open_id','==',me['open_id']]]}),
                   lambda records: len(records) == 1 and records[0].get('已读版本') == patch['已读版本'],
                   'Reading cursor not verified')
    print('仅已更新当前用户的阅读记录。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('setup')
    for name in ['collect','sync']:
        p = sub.add_parser(name)
        p.add_argument('--since', default=(datetime.now(timezone.utc)-timedelta(days=3)).date().isoformat())
        p.add_argument('--output', default=str(Path.home()/'.team-lark/software-snapshot.json'))
        if name == 'sync':
            p.add_argument('--plan')
            p.add_argument('--import-history', action='store_true')
            p.add_argument('--dry-run', action='store_true')
            p.add_argument('--receipt', default=str(Path.home()/'.team-lark/software-receipt.json'))
    for name in ['report','ack']:
        p=sub.add_parser(name)
        p.add_argument('--receipt', default=str(Path.home()/'.team-lark/software-receipt.json'))
    args = parser.parse_args()
    config = json.loads(Path(args.config).expanduser().read_text())
    board = Board(config)
    if args.command == 'setup':
        setup(board, args.config)
        return
    me = whoami(config, verify_github=args.command in ['collect', 'sync'])
    if args.command in ['collect','sync']:
        works = board.list(config['tables']['works'])
        tracked = {u for r in works for u in urls(r)}
        plan = json.loads(Path(args.plan).read_text()) if getattr(args, 'plan', None) else None
        tracked |= {u for r in (plan or {}).get('works', []) for u in r.get('prs', [])}
        try:
            snapshot = collect(config, args.since, tracked)
        except Exception:
            print('GitHub 本轮核实失败；保留飞书最后状态和阅读位置，不把未知当作零或完成。', file=sys.stderr)
            raise
        save(args.output, snapshot)
        if args.command == 'collect':
            print(f"已收集 {len(snapshot['prs'])} PR → {args.output}")
            return
        apply(board, snapshot, plan, me, args.import_history, args.dry_run)
        if args.dry_run:
            return
    if args.command in ['sync','report']:
        report(board, me, args.receipt)
    elif args.command == 'ack':
        ack(board, me, args.receipt)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
