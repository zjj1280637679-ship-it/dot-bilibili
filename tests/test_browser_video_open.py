"""Offline fake-host roundtrips only: no live browser navigation evidence."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from bili_bridge.browser_contracts import HostError, digest
from bili_bridge import browser_video_open_contracts as c
from bili_bridge.browser_host import FileBrowserHost
from bili_bridge.browser_public_search_plugin import BrowserPublicSearchPlugin
from bili_bridge.browser_video_open_plugin import BrowserVideoOpenPlugin
from bili_bridge.browser_video_plugin import BrowserVideoReadPlugin
from bili_bridge.browser_registry import make_request, validate_request, validate_receipt
from bili_bridge.contracts import Request
from bili_bridge.kernel import Kernel
from bili_bridge.cli import main, manifest
from test_browser_public_search import preflight as search_preflight, receipt as search_receipt
from test_browser_video import receipt as video_receipt

BVID='BV9876543210'
URL='https://www.bilibili.com/video/'+BVID+'/'

def selection(now=90):
    return dict(source_operation_id='search',source_scope_digest='a'*64,source_captured_at=now,
        query='test',source_url='https://search.bilibili.com/en/all?keyword=test',source_tab_id='7')

def request():
    return make_request(c.OPERATION,'open','open',BVID,URL,'7',100,100,selection=selection())

def preflight(req,now):
    out={k:req[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest')}
    out.update(observed_source_url=req['source_url'],tab_id=req['source_tab_id'],checked_at=now,
        context='confirmed',selected_bvid=req['bvid'],selected_url=req['destination_url'],selection_visible=True)
    return out

def receipt(req,now):
    out={k:req[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','bvid')}
    out.update(tab_id=req['source_tab_id'],observed_url=req['destination_url'],captured_at=now,
        source='browser_dom',status='observed',phase='capture',context='confirmed',error=None)
    return out

class OpenContracts(unittest.TestCase):
    def test_exact_request_and_tracking_normalization(self):
        req=request(); validate_request(req,110)
        pre=preflight(req,110);pre['selected_url']+='?spm_id_from=333.1'
        self.assertEqual(c.validate_preflight(pre,req,120)['selected_url'],URL)
        out=receipt(req,110);out['observed_url']+='?vd_source=abc'
        self.assertEqual(validate_receipt(out,req,120)['observed_url'],URL)
    def test_no_generic_actions_and_exact_target(self):
        for key,value in [('selector','a'),('script','alert(1)'),('click',True),('destination_url','https://evil.test/'),('effect','write'),('source_url','https://message.bilibili.com/'),('schema_version',True),('bvid','av123'),('source_captured_at',101),('expires_at',1000)]:
            with self.subTest(key=key),self.assertRaises(HostError):
                req=request();req[key]=value;req['scope_digest']=digest(req);validate_request(req,110)
    def test_stale_or_changed_selection_preflight(self):
        req=request()
        for key,value in [('selected_bvid','BV1234567890'),('selected_url',URL+'?p=2'),('selected_url',URL.replace(BVID,'BV1234567890')),('selection_visible',False),('selection_visible',1),('tab_id','8'),('observed_source_url',req['source_url']+'other'),('checked_at',99),('context','changed')]:
            with self.subTest(key=key),self.assertRaises(HostError):
                pre=preflight(req,110);pre[key]=value;c.validate_preflight(pre,req,120)
    def test_receipt_mismatch_and_phase(self):
        req=request()
        for key,value in [('observed_url',None),('observed_url',URL.replace(BVID,'BV1234567890')),('observed_url',URL+'?p=2'),('tab_id','8'),('captured_at',99),('phase','preflight'),('context','changed'),('bvid','BV1234567890')]:
            with self.subTest(key=key),self.assertRaises(HostError):
                out=receipt(req,110);out[key]=value;validate_receipt(out,req,120)
        out=receipt(req,110);out.update(status='blocked',phase='preflight',context='changed',error='target_mismatch',observed_url=None)
        self.assertIsNone(validate_receipt(out,req,120)['observed_url'])
    def test_manifest(self):
        self.assertIn(c.OPERATION,[x['capability'] for x in manifest()['implemented']])
        self.assertEqual(manifest()['serve_capabilities'],['video.metadata'])

class OpenRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.kernel=Kernel(self.root/'journal.db',min_interval=0,hourly_budget=100)
        self.host=FileBrowserHost(self.root/'spool',timeout=.5,cooldown=1)
        self.kernel.register(BrowserPublicSearchPlugin(self.host))
        self.kernel.register(BrowserVideoOpenPlugin(self.host,self.kernel))
        self.kernel.register(BrowserVideoReadPlugin(self.host))
    def tearDown(self):
        self.host.close();self.kernel.close();self.tmp.cleanup()
    def clear_synthetic_cooldown(self):
        # Test clock shortcut, not a production policy bypass or live procedure.
        with self.host._locked():
            state=self.host._read('state.json')
            if state:
                state['cooldown_until']=0;self.host._write('state.json',state)
    def run_host(self,request,worker):
        self.clear_synthetic_cooldown();errors=[]
        def work():
            try:
                deadline=time.monotonic()+2
                while True:
                    try:req=self.host.claim();break
                    except HostError as exc:
                        if str(exc)!='no_active_request' or time.monotonic()>deadline:raise
                        time.sleep(.005)
                worker(req)
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=work);thread.start()
        result=self.kernel.dispatch(request);thread.join()
        self.assertEqual(errors,[])
        return result
    def search(self,operation_id='search'):
        req=Request(operation_id,c.BINDING,'browser.public_search','test',dict(source_url='https://www.bilibili.com/',source_tab_id='7'))
        def worker(req):
            self.host.begin_navigation(search_preflight(req,time.time()))
            out=search_receipt(req,time.time());out['items']=[dict(title='SYNTHETIC',url=URL,bvid=BVID,uploader='sample',duration='1:00',displayed_counts=[])]
            self.host.submit(out)
        result=self.run_host(req,worker);self.assertEqual(result.status,'applied');return result
    def opening(self,operation_id='open',source='search',bvid=BVID):
        return Request(operation_id,c.BINDING,c.OPERATION,bvid,dict(source_operation_id=source))
    def open_worker(self,req):
        with self.assertRaises(HostError):self.host.submit(receipt(req,time.time()))
        pre=preflight(req,time.time());nav=self.host.begin_navigation(pre)
        self.assertEqual(nav,dict(destination_url=URL,tab_id='7'))
        with self.assertRaises(HostError):self.host.begin_navigation(pre)
        with self.assertRaises(HostError):self.host.submit(receipt(req,pre['checked_at']))
        self.host.submit(receipt(req,time.time()))
    def test_search_open_video_read_chain_and_replay(self):
        self.search()
        req=self.opening();result=self.run_host(req,self.open_worker)
        self.assertEqual(result.status,'applied');self.assertEqual(result.data['source_operation_id'],'search')
        self.assertEqual(self.kernel.dispatch(req),result)
        def worker(req):
            out=video_receipt(req);out['captured_at']=time.time();self.host.submit(out)
        read=self.run_host(Request('read',c.BINDING,'browser.video_page.read',BVID,dict(expected_url=URL,expected_tab_id='7')),worker)
        self.assertEqual(read.status,'applied')
        self.assertEqual(self.kernel.dispatch(self.opening('open-again')).error,'selection_already_consumed')
    def test_missing_not_applied_and_nonmember_sources(self):
        self.assertEqual(self.kernel.dispatch(self.opening()).error,'selection_source_not_applied')
        self.search()
        self.assertEqual(self.kernel.dispatch(self.opening('wrong',bvid='BV1234567890')).error,'selection_not_in_snapshot')
    def test_intervening_exchange_invalidates_snapshot(self):
        self.search();self.search('new-search');self.clear_synthetic_cooldown()
        self.assertEqual(self.kernel.dispatch(self.opening()).error,'selection_generation_changed')
    def test_stale_journal_snapshot(self):
        self.search()
        record=self.kernel.status('search');data=record['result'];data['data']['captured_at']=time.time()-601
        with self.kernel._transaction():self.kernel._db.execute('UPDATE operations SET result=? WHERE operation_id=?',(json.dumps(data),'search'))
        self.assertEqual(self.kernel.dispatch(self.opening()).error,'selection_stale')
    def test_timeout_unknown_same_and_new_id_cannot_replay(self):
        self.search();self.clear_synthetic_cooldown()
        req=self.opening();result=self.kernel.dispatch(req)
        self.assertEqual(result.status,'unknown')
        self.assertEqual(self.kernel.dispatch(req),result)
        self.assertEqual(self.kernel.dispatch(self.opening('again')).error,'selection_already_consumed')
        with self.assertRaises(HostError):self.host.claim()
    def test_checkpoint_then_transport_loss_unknown(self):
        self.search()
        def worker(req):self.host.begin_navigation(preflight(req,time.time()))
        self.assertEqual(self.run_host(self.opening(),worker).status,'unknown')
        self.assertEqual(self.kernel.dispatch(self.opening('again')).error,'selection_already_consumed')
    def test_changed_anchor_blocked_before_navigation(self):
        self.search()
        def worker(req):
            pre=preflight(req,time.time());pre['selected_bvid']='BV1234567890'
            with self.assertRaises(HostError):self.host.begin_navigation(pre)
            out=receipt(req,time.time());out.update(status='blocked',phase='preflight',context='changed',observed_url=None,error='target_mismatch');self.host.submit(out)
        self.assertEqual(self.run_host(self.opening(),worker).status,'blocked')
    def test_cli_cannot_accept_caller_url_or_fake_evidence(self):
        self.search();self.clear_synthetic_cooldown()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=main(['--db',str(self.root/'journal.db'),'browser-video-open','--bvid',BVID,'--source-operation-id','missing','--spool',str(self.root/'spool'),'--timeout','1','--operation-id','cli-open'])
        self.assertEqual(code,1);self.assertEqual(json.loads(out.getvalue())['error'],'selection_source_not_applied')
