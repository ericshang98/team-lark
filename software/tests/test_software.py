import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('software', Path(__file__).parents[1]/'scripts/software.py')
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)

CONFIG={'base_token':'test-base','repos':['owner/repo'],'tables':{'works':'w','events':'e','readers':'r'},
        'members':{'alice':{'open_id':'ou_a'},'bob':{'open_id':'ou_b'}}}
ME={'open_id':'ou_a','name':'Alice','github':'alice'}

def pr(n=1,state='OPEN',author='alice',draft=False,review='REVIEW_REQUIRED'):
    return dict(number=n,title=f'Work {n}',state=state,isDraft=draft,author={'login':author},
                url=f'https://github.com/owner/repo/pull/{n}',headRefName='feature',baseRefName='main',
                headRefOid=f'sha{n}',reviewDecision=review,mergeable='MERGEABLE',statusCheckRollup=[])

class FakeBoard:
    def __init__(self):
        self.c=copy.deepcopy(CONFIG)
        self.data={'w':[],'e':[],'r':[]}
        self.mutations=0
        self.race=False
        self.fail_events=False
    def list(self,table,fields=None,condition=None):
        records=copy.deepcopy(self.data[table])
        if condition:
            key,_,value=condition['conditions'][0]
            records=[r for r in records if r.get(key)==value]
        return records
    def get(self,table,rid):
        row=copy.deepcopy(next(r for r in self.data[table] if r['_id']==rid))
        if self.race:
            row['协调事项']='Another writer changed this'
        return row
    def write(self,table,patch,rid=None):
        self.mutations+=1
        if rid:
            next(r for r in self.data[table] if r['_id']==rid).update(copy.deepcopy(patch))
        else:
            self.data[table].append(dict(copy.deepcopy(patch),_id=f'{table}{len(self.data[table])}'))
    def stamp(self,table,rids,patch):
        for rid in rids: self.write(table,patch,rid)
    def batch(self,table,records):
        if table=='e' and self.fail_events and records:
            raise RuntimeError('Injected event failure')
        for r in records: self.write(table,r)

class SoftwareTests(unittest.TestCase):
    def setUp(self):
        self.board=FakeBoard()
        self.snapshot={'prs':[pr()], 'collected_at':'2026-10-29T01:00:00+00:00'}
        self.plan={'works':[{'key':'work-one','owner':'alice','title':'One work',
                              'prs':[pr()['url']], 'coordination':'Wait for interface decision',
                              'validation':'Not deployed', 'summary':'Human explanation'}]}
    def apply(self,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            sw.apply(self.board,self.snapshot,self.plan,ME,**kwargs)
    def test_repeated_sync_has_one_work_and_one_event(self):
        self.apply()
        self.plan=None
        self.snapshot['collected_at']='2026-10-29T02:00:00+00:00'
        self.apply()
        self.assertEqual(len(self.board.data['w']),1)
        self.assertEqual(len(self.board.data['e']),1)
        self.assertEqual(self.board.data['w'][0]['协调事项'],'Wait for interface decision')
    def test_merge_does_not_claim_deployment(self):
        self.apply()
        self.plan=None
        self.snapshot['prs'][0]['state']='MERGED'
        self.apply()
        r=self.board.data['w'][0]
        self.assertEqual(r['开发状态'],'已合并')
        self.assertEqual(r['验证与交付'],'Not deployed')
        self.assertEqual(len(self.board.data['e']),2)
    def test_missing_tracked_pr_fails_before_writes(self):
        self.apply()
        before=copy.deepcopy(self.board.data)
        self.snapshot['prs']=[]
        with self.assertRaisesRegex(RuntimeError,'not verified'):
            self.apply()
        self.assertEqual(self.board.data,before)
    def test_other_member_patch_rejected(self):
        self.plan['works'][0]['owner']='bob'
        with self.assertRaisesRegex(RuntimeError,'another member'):
            self.apply()
        self.assertEqual(self.board.mutations,0)
    def test_dry_run_no_writes(self):
        self.apply(dry_run=True)
        self.assertEqual(self.board.mutations,0)
    def test_concurrent_change_stops(self):
        self.apply()
        before=copy.deepcopy(self.board.data)
        self.board.race=True
        self.plan['works'][0]['summary']='My new summary'
        with self.assertRaisesRegex(RuntimeError,'changed during sync'):
            self.apply()
        self.assertEqual(before,self.board.data)
    def test_event_failure_recovered_without_duplicate_work(self):
        self.board.fail_events=True
        with self.assertRaisesRegex(RuntimeError,'Injected'):
            self.apply()
        self.assertEqual(len(self.board.data['w']),1)
        self.board.fail_events=False
        self.apply()
        self.assertEqual(len(self.board.data['e']),1)
        self.assertEqual(len(self.board.data['w']),1)
    def test_one_pr_cannot_belong_to_two_works(self):
        self.plan['works'].append(dict(self.plan['works'][0],key='another'))
        with self.assertRaisesRegex(RuntimeError,'multiple works'):
            self.apply()
        self.assertEqual(self.board.mutations,0)
    def test_reader_isolation_and_new_update_survives_ack(self):
        self.apply()
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            receipt=Path(d)/'receipt.json'
            sw.report(self.board,ME,receipt)
            self.assertEqual(self.board.data['r'],[])
            old_version=self.board.data['w'][0]['变化ID']
            self.snapshot['prs'][0]['state']='MERGED'
            self.plan=None
            self.apply()
            sw.ack(self.board,ME,receipt)
            seen=json.loads(self.board.data['r'][0]['已读版本'])
            self.assertEqual(seen['work-one'],old_version)
            self.assertNotEqual(seen['work-one'],self.board.data['w'][0]['变化ID'])
            bob=dict(ME,open_id='ou_b',github='bob')
            with self.assertRaisesRegex(RuntimeError,'another reader'):
                sw.ack(self.board,bob,receipt)
            self.assertEqual(len(self.board.data['r']),1)
    def test_draft_review_and_partial_merge(self):
        self.assertEqual(sw.stage([pr(draft=True)]),'开发中')
        self.assertEqual(sw.stage([pr(review='APPROVED')]),'待合并')
        self.assertEqual(sw.stage([pr(state='MERGED'),pr(2)]),'部分合并')
        self.assertEqual(sw.stage([pr(state='CLOSED')]),'已关闭')
    def test_display_names_do_not_change_fingerprint(self):
        a={'负责人':[{'id':'ou_a'}]}
        b={'负责人':[{'id':'ou_a','name':'Alice'}]}
        self.assertEqual(sw.fingerprint(a),sw.fingerprint(b))
    def test_real_lark_select_array_shape(self):
        payload={'fields':['开发状态','负责人'], 'record_id_list':['rec1'],
                 'data':[[['已合并'],[{'id':'ou_a','name':'Alice'}]]], 'has_more':False}
        row=sw.rows(payload)[0]
        self.assertEqual(row['开发状态'],'已合并')
        self.assertEqual(row['负责人'],[{'id':'ou_a'}])
    def test_closed_checks_not_collected_is_explicit(self):
        p=pr(state='MERGED');p['checksCollected']=False
        self.assertIn('未采集',sw.machine_patch([p])['检查与评审'])
    def test_network_retries_reads_not_writes(self):
        from unittest.mock import patch
        with patch.object(sw,'run_once',side_effect=[RuntimeError('502'), {'ok':True}]) as call, patch.object(sw.time,'sleep'):
            self.assertEqual(sw.run(['lark-cli','base','+record-list']), {'ok':True})
            self.assertEqual(call.call_count,2)
        with patch.object(sw,'run_once',side_effect=RuntimeError('502')) as call:
            with self.assertRaises(RuntimeError): sw.run(['lark-cli','base','+record-upsert'])
            self.assertEqual(call.call_count,1)
    def test_eventual_read_is_retried_without_duplicate_write(self):
        from unittest.mock import patch
        answers=iter([[],[],['event']])
        with patch.object(sw.time,'sleep'):
            self.assertEqual(sw.confirmed_read(lambda:next(answers),lambda x:'event'in x,'missing'), ['event'])
    def test_multiple_recent_updates_preserve_human_notes(self):
        self.apply()
        self.board.data['w'][0]['协调事项']='User edited in Feishu'
        self.plan=None
        self.snapshot['prs'][0]['headRefOid']='sha-new'
        self.apply()
        self.assertEqual(self.board.data['w'][0]['协调事项'],'User edited in Feishu')
        self.assertEqual(len(self.board.data['e']),2)
    def test_unchecked_is_not_passed(self):
        self.assertIn('无检查记录',sw.machine_patch([pr()])['检查与评审'])

if __name__=='__main__': unittest.main()
