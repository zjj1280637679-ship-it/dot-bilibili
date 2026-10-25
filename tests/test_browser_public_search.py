"""Offline synthetic protocol tests; not live DOM/navigation evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from bili_bridge import browser_public_search_contracts as c
from bili_bridge.browser_contracts import HostError, digest
from bili_bridge.browser_registry import make_request, validate_request, validate_receipt
from bili_bridge.browser_host import FileBrowserHost
from bili_bridge.cli import main, manifest

SOURCE = 'https://www.bilibili.com/video/BV9876543210/'

def request():
    return make_request(c.OPERATION, 'public-test', 'public-test', '中文 & 100%', SOURCE, '7', 100, 100)

def preflight(req, now):
    out = {k:req[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest')}
    out.update(observed_source_url=req['source_url'], tab_id=req['source_tab_id'], checked_at=now, context='confirmed')
    return out

def receipt(req, now):
    out = {k:req[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','query')}
    out.update(tab_id=req['source_tab_id'],observed_url=req['destination_url'],captured_at=now,source='browser_dom',status='observed',phase='capture',context='confirmed',items=[],error=None)
    return out

class PublicSearchTests(unittest.TestCase):
    def test_generated_destination_and_canonicalization(self):
        req=request(); self.assertEqual(req['destination_url'],'https://search.bilibili.com/en/all?keyword=%E4%B8%AD%E6%96%87+%26+100%25')
        out=receipt(req,110);out['observed_url'] += '&spm_id_from=333.1007&from_source=web'
        self.assertEqual(validate_receipt(out,req,120)['observed_url'],req['destination_url'])
        self.assertEqual(c.source_url(SOURCE+'?vd_source=abc'),SOURCE)
        self.assertEqual(c.source_url('https://search.bilibili.com/en/all?keyword=test&spm_id_from=333.1'),'https://search.bilibili.com/en/all?keyword=test')
    def test_reject_semantic_query_and_destinations(self):
        req=request()
        for suffix in ('&p=2','&page=2','&order=click','&filter=1','&keyword=other','&spm_id_from=%zz','#x','&token=secret','&spm_id_from='):
            with self.subTest(suffix=suffix), self.assertRaises(HostError):
                out=receipt(req,110);out['observed_url']+=suffix;validate_receipt(out,req,120)
        for url in ('https://message.bilibili.com/','https://www.bilibili.com/account','https://www.bilibili.com:443/video/BV9876543210/',SOURCE+'?p=2'):
            with self.assertRaises(HostError):c.source_url(url)
        for query in ('',' ','x'*201,'x\nx','\ud800'):
            with self.assertRaises(HostError):c.destination(query)
    def test_request_identity_and_explicit_schema(self):
        for key,value in [('script','x'),('selector','body'),('destination_url','https://evil.test'),('effect','write'),('source_url',SOURCE+'?vd_source=abc'),('schema_version',True)]:
            with self.subTest(key=key),self.assertRaises(HostError):
                req=request();req[key]=value;req['scope_digest']=digest(req);validate_request(req,120)
        for key,value in [('context','changed'),('context','unavailable'),('phase','preflight'),('tab_id','8'),('captured_at',99),('captured_at',121),('operation','browser.search_results.read')]:
            with self.subTest(key=key),self.assertRaises(HostError):
                req=request();out=receipt(req,110);out[key]=value;validate_receipt(out,req,120)
    def test_preflight_strict_and_sanitized(self):
        req=request();pre=preflight(req,110);pre['observed_source_url']+='?vd_source=abc'
        self.assertEqual(c.validate_preflight(pre,req,120)['observed_source_url'],SOURCE)
        for key,value in [('tab_id','8'),('observed_source_url',SOURCE.replace('3210','3211')),('checked_at',99),('checked_at',121),('context','changed'),('context','unavailable'),('scope_digest','wrong')]:
            with self.subTest(key=key),self.assertRaises(HostError):
                pre=preflight(req,110);pre[key]=value;c.validate_preflight(pre,req,120)
    def test_preflight_blocked_without_fake_destination(self):
        req=request();out=receipt(req,110)
        out.update(status='blocked',phase='preflight',observed_url=None,context='unavailable',error='context_unavailable')
        validate_receipt(out,req,120)
        out['observed_url']=req['destination_url']
        with self.assertRaises(HostError):validate_receipt(out,req,120)
    def test_cli_roundtrip_durable_phase_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            host=FileBrowserHost(Path(directory)/'spool');errors=[]
            def worker():
                try:
                    deadline=time.monotonic()+3
                    while True:
                        try:req=host.claim();break
                        except HostError as exc:
                            if str(exc) != 'no_active_request' or time.monotonic()>=deadline:raise
                            time.sleep(.01)
                    with self.assertRaises(HostError):host.submit(receipt(req,time.time()))
                    pre=preflight(req,time.time());result=host.begin_navigation(pre)
                    self.assertEqual(result,{'destination_url':req['destination_url'],'tab_id':'7'})
                    with self.assertRaises(HostError):host.begin_navigation(pre)
                    stale=receipt(req,pre['checked_at'])
                    with self.assertRaises(HostError):host.submit(stale)
                    with host._locked():
                        state=host._read('state.json');self.assertIn('navigation_started_at',state)
                        self.assertNotIn('vd_source',json.dumps(state))
                    out=receipt(req,time.time());out['observed_url']+='&spm_id_from=333.1'
                    host.submit(out)
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=worker);thread.start()
            args=['--db',str(Path(directory)/'journal.db'),'browser-public-search','--query','test','--source-url',SOURCE+'?vd_source=abc','--tab','7','--spool',str(Path(directory)/'spool'),'--timeout','3','--operation-id','public-cli']
            output=io.StringIO()
            with contextlib.redirect_stdout(output):code=main(args)
            thread.join();self.assertEqual(errors,[]);self.assertEqual(code,0)
            result=json.loads(output.getvalue());self.assertEqual(result['status'],'applied');self.assertIn('browser.host.public_search',result['data']['relay_trace'])
            self.assertNotIn('vd_source',output.getvalue())
            output=io.StringIO()
            with contextlib.redirect_stdout(output):self.assertEqual(main(args),0)
            with self.assertRaises(HostError):host.claim()
            host.close()
    def test_public_homepage_sources_preserve_locale(self):
        for url, canonical in [
            ('https://www.bilibili.com/', 'https://www.bilibili.com/'),
            ('https://www.bilibili.com/en', 'https://www.bilibili.com/en'),
            ('https://www.bilibili.com/en/', 'https://www.bilibili.com/en')]:
            with self.subTest(url=url):
                self.assertEqual(c.source_url(url), canonical)
                req = make_request(c.OPERATION, 'home', 'home', 'test', url, '3', 100, 100)
                self.assertEqual(req['source_url'], canonical)
                self.assertEqual(req['destination_url'], c.destination('test'))
                pre = preflight(req, 110); pre['observed_source_url'] = url
                self.assertEqual(c.validate_preflight(pre, req, 120)['observed_source_url'], canonical)
        req = make_request(c.OPERATION, 'home', 'home', 'test', 'https://www.bilibili.com/', '3', 100, 100)
        pre = preflight(req, 110); pre['observed_source_url'] = 'https://www.bilibili.com/en'
        with self.assertRaises(HostError): c.validate_preflight(pre, req, 120)

    def test_homepage_sources_reject_private_routes_and_url_extras(self):
        for url in [
            'https://www.bilibili.com', 'https://www.bilibili.com/en//',
            'http://www.bilibili.com/en', 'https://www.bilibili.com:443/en',
            'https://user@www.bilibili.com/en', 'https://www.bilibili.com.evil.test/en',
            'https://www.bilibili.com/en?', 'https://www.bilibili.com/en#',
            'https://www.bilibili.com/en?spm_id_from=333.1',
            'https://www.bilibili.com/en#fragment', 'https://www.bilibili.com/%65n',
            'https://message.bilibili.com/', 'https://www.bilibili.com/message',
            'https://www.bilibili.com/history', 'https://www.bilibili.com/account',
            'https://www.bilibili.com/en/account', 'https://www.bilibili.com/account/../en']:
            with self.subTest(url=url), self.assertRaises(HostError): c.source_url(url)

    def test_manifest(self):
        m=manifest();self.assertIn(c.OPERATION,[x['capability'] for x in m['implemented']]);self.assertNotIn(c.OPERATION,m['serve_capabilities'])
