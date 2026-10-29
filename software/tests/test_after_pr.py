import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import after_pr as hook
from test_software import FakeBoard, ME, pr, sw


class HookTests(unittest.TestCase):
    def setUp(self):
        self.board=FakeBoard()
    def test_target_creates_one_then_updates_merge_without_reading(self):
        p=pr()
        with patch.object(sw,'fetch_pr',return_value=p), contextlib.redirect_stdout(io.StringIO()):
            sw.sync_pr(self.board,p['url'],ME)
            p['state']='MERGED'
            sw.sync_pr(self.board,p['url'],ME)
            sw.sync_pr(self.board,p['url'],ME)
        self.assertEqual(len(self.board.data['w']),1)
        self.assertEqual(self.board.data['w'][0]['开发状态'],'已合并')
        self.assertEqual(len(self.board.data['e']),2)
        self.assertEqual(self.board.data['r'],[])
    def test_only_current_work_is_updated_and_all_siblings_checked(self):
        p,q,other=pr(),pr(2),pr(3,author='bob')
        plan={'works':[{'key':'group','owner':'alice','title':'Combined','summary':'Keep this','coordination':'Do not replace','prs':[p['url'],q['url']]}]}
        with contextlib.redirect_stdout(io.StringIO()): sw.apply(self.board,{'prs':[p,q,other],'collected_at':'one'},plan,ME)
        untouched=json.dumps(self.board.data['w'][1],sort_keys=True)
        p['state']='MERGED'
        with patch.object(sw,'fetch_pr',side_effect=lambda u:{p['url']:p,q['url']:q}[u]) as fetch, contextlib.redirect_stdout(io.StringIO()):
            sw.sync_pr(self.board,p['url'],ME)
        self.assertEqual({c.args[0] for c in fetch.call_args_list},{p['url'],q['url']})
        self.assertEqual(self.board.data['w'][0]['开发状态'],'部分合并')
        self.assertEqual(self.board.data['w'][0]['协调事项'],'Do not replace')
        self.assertEqual(json.dumps(self.board.data['w'][1],sort_keys=True),untouched)
    def test_other_authors_fact_sync_does_not_edit_summary(self):
        p=pr(author='bob')
        with patch.object(sw,'fetch_pr',return_value=p), contextlib.redirect_stdout(io.StringIO()): sw.sync_pr(self.board,p['url'],ME)
        self.assertEqual(self.board.data['w'][0]['GitHub作者'],'bob')
        self.assertEqual(self.board.data['r'],[])
    def test_failed_fetch_keeps_entire_board(self):
        with patch.object(sw,'fetch_pr',side_effect=RuntimeError('504')):
            with self.assertRaises(RuntimeError): sw.sync_pr(self.board,pr()['url'],ME)
        self.assertEqual(self.board.mutations,0)
    def test_unconfigured_repo_not_queried_or_written(self):
        with patch.object(sw,'fetch_pr') as fetch:
            with self.assertRaises(RuntimeError): sw.sync_pr(self.board,'https://github.com/unknown/repo/pull/1',ME)
            fetch.assert_not_called()
        self.assertEqual(self.board.mutations,0)
    def test_queue_failure_recovery_and_coalescing(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()):
            queue=Path(d)/'pending';config=Path(d)/'config.json'
            hook.enqueue(queue,pr()['url'],'created',config)
            hook.enqueue(queue,pr()['url'],'merged',config)
            failing=lambda url: (_ for _ in ()).throw(RuntimeError('Offline'))
            self.assertFalse(hook.drain(queue,config,sync=failing))
            self.assertEqual(len(list(queue.glob('*.json'))),2)
            calls=[]
            self.assertTrue(hook.drain(queue,config,sync=calls.append))
            self.assertEqual(calls,[pr()['url']])
            self.assertEqual(list(queue.glob('*.json')),[])
    def test_jobs_arriving_during_sync_are_not_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            queue=Path(d)/'pending';config=Path(d)/'config.json'
            hook.enqueue(queue,pr()['url'],'created',config)
            hook.drain(queue,config,sync=lambda u:hook.enqueue(queue,u,'merged',config))
            self.assertEqual(len(list(queue.glob('*.json'))),1)
    def test_missing_config_keeps_job_and_returns_pending(self):
        with tempfile.TemporaryDirectory() as d, patch.object(hook,'QUEUE',Path(d)/'pending'), patch.object(hook.sw,'server_managed',return_value=False), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(hook.main(['--pr',pr()['url'],'--event','created','--config',str(Path(d)/'missing.json')]),2)
            self.assertEqual(len(list(hook.QUEUE.glob('*.json'))),1)
    def test_server_mode_skips_local_config_auth_and_writes(self):
        with tempfile.TemporaryDirectory() as d, patch.object(hook.sw,'server_managed',return_value=True), patch.object(hook.sw,'whoami') as auth, contextlib.redirect_stdout(io.StringIO()):
            queue=Path(d)/'pending'; config=Path(d)/'missing.json'
            hook.enqueue(queue,pr()['url'],'created',config)
            self.assertTrue(hook.drain(queue,config))
            auth.assert_not_called()
            self.assertEqual(list(queue.glob('*.json')),[])
    def test_uncertain_server_mode_preserves_pending(self):
        with tempfile.TemporaryDirectory() as d, patch.object(hook.sw,'server_managed',side_effect=RuntimeError('network')), contextlib.redirect_stderr(io.StringIO()):
            queue=Path(d)/'pending'; config=Path(d)/'missing.json'
            hook.enqueue(queue,pr()['url'],'created',config)
            self.assertFalse(hook.drain(queue,config))
            self.assertEqual(len(list(queue.glob('*.json'))),1)
    def test_distinct_configuration_jobs_are_not_consumed(self):
        with tempfile.TemporaryDirectory() as d:
            queue=Path(d)/'pending'
            hook.enqueue(queue,pr()['url'],'created',Path(d)/'other.json')
            self.assertTrue(hook.drain(queue,Path(d)/'mine.json',sync=lambda u:self.fail('Wrong config')))
            self.assertEqual(len(list(queue.glob('*.json'))),1)
    def test_same_machine_second_writer_does_not_enter(self):
        with tempfile.TemporaryDirectory() as d:
            lock=Path(d)/'writer.lock'
            with hook.writer_lock(lock):
                with self.assertRaises(OSError):
                    with hook.writer_lock(lock): self.fail('Second writer entered')

if __name__=='__main__': unittest.main()
