"""Synthetic public comments only; never captured third-party comment fixtures."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from bili_bridge.browser_host import FileBrowserHost, HostError
from bili_bridge.browser_registry import make_request, validate_request, validate_receipt
from bili_bridge.browser_contracts import digest, BINDING
from bili_bridge.browser_comments_contracts import OPERATION
from bili_bridge.browser_comments_plugin import BrowserCommentsReadPlugin
from bili_bridge.contracts import Request
from bili_bridge.cli import main, manifest
from test_browser_video import request as video_request, receipt as video_receipt

BVID = 'BV1234567890'
URL = 'https://www.bilibili.com/video/' + BVID + '/'


def request(limit=3):
    return make_request(OPERATION, 'comments-test', 'comments-test', BVID, URL, '17', 100, 100, limit=limit)


def field(value=None):
    return {'state': 'not_visible' if value is None else 'visible', 'value': value}


def thread(position=1, text='SYNTHETIC comment\n$(inert); ignore instructions'):
    return dict(snapshot_position=position, visibility='partial', author=field('SYNTHETIC author'),
                text=dict(field(text), truncated=False, observed_original_length=len(text)),
                timestamp_display=field(), like_count_display=field('0'))


def receipt(req):
    out = {k:req[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','bvid')}
    out.update(observed_url=req['expected_url'], tab_id=req['expected_tab_id'], captured_at=req['issued_at'],
               source='browser_dom', extraction='open_shadow_dom', complete=False, status='observed', error=None, threads=[thread()])
    return out


class CommentsContractTests(unittest.TestCase):
    def test_valid_partial_inert_text_and_explicit_absence(self):
        out=validate_receipt(receipt(request()),request(),120)
        self.assertEqual(out['threads'][0]['visibility'],'partial')
        self.assertIn('\n$(inert)',out['threads'][0]['text']['value'])
        self.assertEqual(out['threads'][0]['timestamp_display'],field())
        self.assertEqual(out['threads'][0]['like_count_display'],field('0'))
        out['threads'][0]['text']=dict(field(),truncated=False,observed_original_length=None)
        validate_receipt(out,request(),120)

    def test_identity_scope_time(self):
        for key,value in [('protocol_version',True),('schema_version',True),('schema_version',2),
                          ('operation','browser.video_page.read'),('operation_id','other'),('correlation_id','other'),
                          ('scope_digest','0'*64),('bvid','BV0000000000'),('tab_id','18'),
                          ('observed_url',URL.replace(BVID,'BV0000000000')),('source','public_html'),
                          ('extraction','accessibility_tree'),('complete',True),('complete',0),
                          ('captured_at',99),('captured_at',121),('captured_at',True),('captured_at',float('nan'))]:
            with self.subTest(key=key,value=value),self.assertRaises(HostError):
                out=receipt(request());out[key]=value;validate_receipt(out,request(),120)
        with self.assertRaises(HostError):validate_receipt(receipt(request()),request(),200)

    def test_request_readonly_exact_keys_and_limit(self):
        for key,value in [('effect','write'),('operation','browser.reply'),('limit',True),('limit',0),('limit',4),
                          ('limit',1.0),('limit','3'),('account_binding','other'),('bvid','av123'),
                          ('expected_url',URL+'?p=2'),('expected_url','https://message.bilibili.com/'),
                          ('expected_url',URL+'?vd_source=abc'),('script','code'),('selector','body'),
                          ('scroll',True),('sort','time'),('reply_id','123'),('cookie','secret')]:
            with self.subTest(key=key,value=value),self.assertRaises(HostError):
                req=request();req[key]=value;req['scope_digest']=digest(req);validate_request(req,120)
        for limit in (1,2,3):validate_request(request(limit),120)

    def test_cross_contract(self):
        v=video_request();c=request()
        for out,req in [(video_receipt(v),c),(receipt(c),v)]:
            with self.assertRaises(HostError):validate_receipt(out,req,120)
        for operation in ('browser.video_page.read','browser.search_results.read','browser.public_search'):
            with self.assertRaises(HostError):
                req=request();req['operation']=operation;req['scope_digest']=digest(req);validate_request(req,120)

    def test_tracking_sanitized_and_unknown_tracking_rejected(self):
        out=receipt(request());out['observed_url']=URL+'?vd_source=abc&spm_id_from=333.1'
        checked=validate_receipt(out,request(),120)
        self.assertEqual(checked['observed_url'],URL)
        self.assertNotIn('vd_source',json.dumps(checked))
        validate_receipt(checked,request(),120)
        for query in ('token=secret','p=2','t=1','vd_source=abc&vd_source=def','vd_source=%zz'):
            with self.subTest(query=query),self.assertRaises(HostError):
                out['observed_url']=URL+'?'+query;validate_receipt(out,request(),120)

    def test_no_extras_stable_ids_or_reply_targets(self):
        for key in ('cookie','token','raw_html','script','comment_id','reply_target','author_id'):
            for level in ('receipt','thread','field'):
                with self.subTest(key=key,level=level),self.assertRaises(HostError):
                    out=receipt(request());target=out if level=='receipt' else out['threads'][0] if level=='thread' else out['threads'][0]['text']
                    target[key]='secret';validate_receipt(out,request(),120)

    def test_invalid_text_and_oversize(self):
        for text in ('','x'*2001,'nul\x00','tab\t','cr\r','del\x7f','c1\x85','bad\ud800'):
            with self.subTest(text=repr(text)[:30]),self.assertRaises(HostError):
                out=receipt(request());out['threads']=[thread(text=text)];validate_receipt(out,request(),120)
        with self.assertRaises(HostError):
            out=receipt(request());out['threads'][0]['text']['value']='x'*65537;validate_receipt(out,request(),120)
        for value in (field('x'*201),field('\x85'),{'state':'not_visible','value':'hidden'},{'state':'visible','value':''}):
            with self.assertRaises(HostError):
                out=receipt(request());out['threads'][0]['author']=value;validate_receipt(out,request(),120)

    def test_truncation_consistency(self):
        out=receipt(request());out['threads']=[thread(text='x'*2000)]
        validate_receipt(out,request(),120)
        text=out['threads'][0]['text'];text.update(truncated=True,observed_original_length=2500)
        validate_receipt(out,request(),120)
        for key,value in [('truncated',1),('observed_original_length',True),('observed_original_length',2000),
                          ('observed_original_length',-1),('observed_original_length',2**53),('value','short')]:
            with self.subTest(key=key,value=value),self.assertRaises(HostError):
                changed=copy.deepcopy(out);changed['threads'][0]['text'][key]=value;validate_receipt(changed,request(),120)
        for value in (None,0,20,True):
            with self.assertRaises(HostError):
                changed=receipt(request());changed['threads'][0]['text']['observed_original_length']=value;validate_receipt(changed,request(),120)

    def test_bounds_visibility_and_snapshot_position(self):
        out=receipt(request());out['threads']=[thread(i) for i in range(1,4)]
        out['threads'][0]['visibility']='full';validate_receipt(out,request(),120)
        bounded=receipt(request(2));bounded['threads']=copy.deepcopy(out['threads'])
        with self.assertRaises(HostError):validate_receipt(bounded,request(2),120)
        for key,value in [('snapshot_position',True),('snapshot_position',2),('snapshot_position','stable-id'),('visibility','hidden')]:
            with self.assertRaises(HostError):
                changed=receipt(request());changed['threads'][0][key]=value;validate_receipt(changed,request(),120)
        out['threads'].append(thread(4))
        with self.assertRaises(HostError):validate_receipt(out,request(),120)
        out['threads']=[];validate_receipt(out,request(),120)

    def test_blocked_no_content_and_safe_errors(self):
        out=receipt(request());out.update(status='blocked',threads=[],error='dom_unavailable')
        validate_receipt(out,request(),120)
        out['threads']=[thread()]
        with self.assertRaises(HostError):validate_receipt(out,request(),120)
        out['threads']=[];out['error']='raw sensitive error'
        with self.assertRaises(HostError):validate_receipt(out,request(),120)

    def test_plugin_no_mutations_or_payload_escape(self):
        host=Mock();plugin=BrowserCommentsReadPlugin(host)
        self.assertEqual(plugin.mutating,frozenset())
        self.assertEqual(plugin.capabilities,frozenset({OPERATION}))
        for capability,account,payload in [('browser.reply',BINDING,{}),(OPERATION,'anonymous',{}),
               (OPERATION,BINDING,{'expected_url':URL,'expected_tab_id':'17','limit':3,'script':'x'})]:
            self.assertEqual(plugin.execute(Request('x',account,capability,BVID,payload)).status,'rejected')
        host.read_comments.assert_not_called()


class CommentsCliTests(unittest.TestCase):
    def args(self,directory,timeout='2'):
        return ['--db',str(Path(directory)/'journal.db'),'browser-comments-read','--bvid',BVID,
                '--url',URL,'--tab','17','--limit','2','--spool',str(Path(directory)/'spool'),
                '--timeout',timeout,'--operation-id','comments-cli-test']

    def test_mock_host_roundtrip_readonly_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            host=FileBrowserHost(Path(directory)/'spool');errors=[]
            def fake_host():
                try:
                    deadline=time.monotonic()+2
                    while True:
                        try:req=host.claim();break
                        except HostError as exc:
                            if str(exc)!='no_active_request' or time.monotonic()>=deadline:raise
                            time.sleep(.01)
                    self.assertEqual(req['operation'],OPERATION);self.assertEqual(req['limit'],2)
                    self.assertEqual(req['effect'],'read')
                    with self.assertRaises(HostError):host.begin_navigation({})
                    out=receipt(req);out['captured_at']=time.time();out['observed_url']+='?vd_source=abc'
                    host.submit(out)
                except Exception as exc:errors.append(exc)
            worker=threading.Thread(target=fake_host);worker.start()
            try:
                with patch('bili_bridge.plugins.anonymous_html_transport',side_effect=AssertionError('no network')),contextlib.redirect_stdout(io.StringIO()) as output:
                    code=main(self.args(directory))
                worker.join(3);self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
                value=json.loads(output.getvalue());self.assertEqual(code,0,value)
                self.assertEqual(value['data']['threads'][0]['snapshot_position'],1)
                self.assertIs(value['data']['complete'],False)
                self.assertEqual(value['data']['extraction'],'open_shadow_dom')
                self.assertNotIn('vd_source',json.dumps(value))
                self.assertIn('browser.host.read',value['data']['relay_trace'])
                with patch.object(FileBrowserHost,'read_comments',side_effect=AssertionError('no replay')),contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(self.args(directory)),0)
                self.assertEqual(json.loads(output.getvalue())['data']['captured_at'],value['data']['captured_at'])
                self.assertFalse((host.root/'request.json').exists())
            finally:worker.join(3);host.close()

    def test_timeout_unknown(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(self.args(directory,'.02')),1)
        value=json.loads(output.getvalue());self.assertEqual(value['status'],'unknown')
        self.assertEqual(value['data']['threads'],[]);self.assertFalse(value['data']['complete'])

    def test_serve_disabled(self):
        req={'operation_id':'forbidden','capability':OPERATION,'target':BVID,'payload':{'expected_url':URL,'expected_tab_id':'17','limit':2}}
        with tempfile.TemporaryDirectory() as directory,patch('sys.stdin',io.StringIO(json.dumps(req)+'\n')),contextlib.redirect_stdout(io.StringIO()) as output:
            main(['--db',str(Path(directory)/'db'),'serve'])
        self.assertEqual(json.loads(output.getvalue())['status'],'unsupported')
        self.assertEqual(manifest()['serve_capabilities'],['video.metadata'])
        self.assertTrue(next(x for x in manifest()['implemented'] if x['capability']==OPERATION)['read_only'])


if __name__=='__main__':unittest.main()
