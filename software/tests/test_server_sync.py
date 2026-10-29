import contextlib
import copy
import io
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import server_sync as server
from test_software import CONFIG, FakeBoard, pr


class ServerTests(unittest.TestCase):
    def board(self):
        obj = server.FeishuBoard.__new__(server.FeishuBoard)
        obj.c = copy.deepcopy(CONFIG)
        obj.allowed = {'w', 'e'}
        obj.validated = {}
        obj.token = 'test'
        return obj

    def test_no_personal_identity_and_no_reader_writes(self):
        b = FakeBoard()
        with patch.object(server.sw, 'collect', return_value={'prs': [pr(), pr(2, author='bob')], 'collected_at': '2026-10-29T00:00:00+00:00'}), contextlib.redirect_stdout(io.StringIO()):
            server.reconcile(b, 'owner/repo')
            server.reconcile(b, 'owner/repo')
        self.assertEqual(len(b.data['w']), 2)
        self.assertEqual(len(b.data['e']), 2)
        self.assertEqual(b.data['r'], [])

    def test_new_run_recovers_other_pr_merge_and_missing_event(self):
        b = FakeBoard()
        snapshot = {'prs': [pr(), pr(2)], 'collected_at': '2026-10-29T00:00:00+00:00'}
        with patch.object(server.sw, 'collect', return_value=snapshot), contextlib.redirect_stdout(io.StringIO()):
            server.reconcile(b, 'owner/repo')
            b.data['e'].pop()
            b.data['w'][0]['工作摘要'] = 'Keep human context'
            snapshot['prs'][0]['state'] = 'MERGED'
            server.reconcile(b, 'owner/repo')
        self.assertEqual(b.data['w'][0]['开发状态'], '已合并')
        self.assertEqual(b.data['w'][0]['工作摘要'], 'Keep human context')
        self.assertEqual(len(b.data['e']), 3)

    def test_github_failure_preserves_board(self):
        b = FakeBoard()
        with patch.object(server.sw, 'collect', side_effect=RuntimeError('outage')):
            with self.assertRaises(RuntimeError): server.reconcile(b, 'owner/repo')
        self.assertEqual(b.mutations, 0)

    def test_wrong_repo_rejected_before_read(self):
        b = FakeBoard()
        with self.assertRaises(ValueError): server.reconcile(b, 'attacker/repo')
        self.assertEqual(b.mutations, 0)

    def test_cross_repo_link_rejected(self):
        b = FakeBoard()
        b.data['w'] = [{'PR链接': 'https://github.com/another/repo/pull/1'}]
        with self.assertRaises(ValueError): server.reconcile(b, 'owner/repo')

    def test_pagination_and_normalization(self):
        b = self.board()
        pages = [{'items': [{'record_id':'r1','fields':{'负责人':[{'id':'ou_a','name':'A'}],'开发状态':'已合并'}}], 'has_more':True, 'page_token':'next'},
                 {'items': [{'record_id':'r2','fields':{'工作内容':[{'text':'Title'}]}}], 'has_more':False}]
        with patch.object(b, 'request', side_effect=pages) as request:
            rows = b.list('w')
        self.assertIn('page_token=next', request.call_args.args[1])
        self.assertEqual(rows[0]['负责人'], [{'id':'ou_a'}])
        self.assertEqual(rows[1]['工作内容'], 'Title')
        self.assertEqual(rows[0]['开发状态'], '已合并')

    def test_readers_access_denied(self):
        with self.assertRaises(ValueError): self.board().list('r')

    def test_no_blind_write_retry(self):
        b = self.board()
        with patch.object(server.urllib.request, 'urlopen', side_effect=server.urllib.error.URLError('timeout')) as call:
            with self.assertRaises(RuntimeError): b.request('POST', '/test', {'private':'never print'})
        self.assertEqual(call.call_count, 1)

    def test_api_errors_do_not_echo_secrets(self):
        b = self.board()
        response = io.BytesIO(b'{"code":99991672,"msg":"secret data"}')
        with patch.object(server.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'code=99991672') as caught: b.request('GET', '/test')
        self.assertNotIn('secret data', str(caught.exception))

    def test_read_retry_is_bounded(self):
        b = self.board()
        with patch.object(server.urllib.request, 'urlopen', side_effect=server.urllib.error.URLError('timeout')) as call, patch.object(server.time, 'sleep'):
            with self.assertRaises(RuntimeError): b.request('GET', '/test')
        self.assertEqual(call.call_count, 3)

    def test_earliest_checkpoint_survives_interruption(self):
        self.assertEqual(server.recovery_since([{'最近核实UTC':'2026-10-15T00:00:00+00:00'}, {'最近核实UTC':'2026-10-29T00:00:00+00:00'}]), '2026-10-14')

    def test_bad_schema_stops_before_write(self):
        b = self.board()
        with patch.object(b, 'pages', return_value=[{'field_name':'existing'}]), patch.object(b, 'request') as call:
            with self.assertRaises(RuntimeError): b.write('w', {'missing': 'value'})
        call.assert_not_called()

if __name__ == '__main__': unittest.main()
