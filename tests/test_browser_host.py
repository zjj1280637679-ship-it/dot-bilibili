import copy
import subprocess
import sys
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from bili_bridge.browser_host import *

class BrowserHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = FileBrowserHost(Path(self.temp.name)/'spool', timeout=2, cooldown=1)
        self.req = dict(protocol_version=1, operation_id='op', correlation_id='op', operation=OPERATION,
                        account_binding=BINDING, effect='read', query='hello world', expected_url='https://search.bilibili.com/en/all?keyword=hello%20world&from_source=web_search', expected_tab_id='6', issued_at=time.time()-1, expires_at=time.time()+30)
        self.req['scope_digest'] = digest(self.req)

    def tearDown(self):
        self.host.close()
        self.temp.cleanup()

    def receipt(self, req=None):
        req = req or self.req
        return dict(protocol_version=1, operation_id=req['operation_id'], correlation_id=req['correlation_id'], scope_digest=req['scope_digest'], observed_url=req['expected_url'], tab_id=req['expected_tab_id'], query=req['query'], captured_at=time.time(), source='browser_dom', status='observed', error=None, items=[dict(title='hello',url='https://www.bilibili.com/en/video/BV1234567890', bvid='BV1234567890',uploader='u',duration='3:12',displayed_counts=['1.2万播放'])])

    def start(self):
        result = []
        def run():
            try:
                result.append(self.host.read('live', 'live', self.req['query'], self.req['expected_url'], '6'))
            except Exception as e:
                result.append(e)
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.time()+2
        while not (self.host.root/'request.json').exists() and time.time()<deadline:
            time.sleep(.01)
        return thread, result

    def test_roundtrip_and_cooldown(self):
        thread, result = self.start()
        req = self.host.claim()
        with self.assertRaisesRegex(HostError, 'already_claimed'):
            self.host.claim()
        self.host.submit(self.receipt(req))
        with self.assertRaises(HostError):
            self.host.submit(self.receipt(req))
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(result[0], dict)
        self.assertEqual(result[0]['items'][0]['url'], 'https://www.bilibili.com/video/BV1234567890/')
        with self.assertRaisesRegex(HostError, 'host_cooldown'):
            self.host.read('other','other',self.req['query'],self.req['expected_url'],'6')
        self.assertFalse((self.host.root/'request.json').exists())

    def test_timeout_unknown_no_reuse(self):
        self.host.timeout = .15
        thread, result = self.start()
        req = self.host.claim()
        thread.join(2)
        self.assertEqual(str(result[0]), 'host_outcome_unknown')
        with self.assertRaisesRegex(HostError, 'no_active_request'):
            self.host.submit(self.receipt(req))
        self.assertEqual(self.host._read('state.json')['status'],'unknown')

    def test_independent_helper_processes(self):
        thread, result = self.start()
        helper = [sys.executable, 'scripts/browser_host_exchange.py', '--spool', str(self.host.root)]
        claim = subprocess.run(helper+['claim'], capture_output=True, text=True, check=True)
        req = json.loads(claim.stdout)
        receipt_path = Path(self.temp.name)/'receipt.json'
        receipt_path.write_text(json.dumps(self.receipt(req)))
        submitted = subprocess.run(helper+['submit','--receipt',str(receipt_path)], capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(submitted.stdout)['accepted'])
        thread.join(3)
        self.assertIsInstance(result[0], dict)

    def test_receipt_rejections(self):
        mutations = [('operation_id','different'),('correlation_id','different'),('scope_digest','0'*64),('tab_id','7'),('query','different'),('source','fixture'),('captured_at',self.req['issued_at']-1),('captured_at',time.time()+100),('observed_url','https://evil.com'),('protocol_version',True),('error','raw secret')]
        for k,v in mutations:
            with self.subTest(k=k,v=v), self.assertRaises(HostError):
                r=self.receipt();r[k]=v;validate_receipt(r,self.req)
        r=self.receipt(); r['cookie']='secret'
        with self.assertRaisesRegex(HostError,'receipt_schema'):
            validate_receipt(r,self.req)
        r=self.receipt();r['items'][0]['url']='https://evil.com/video/BV1234567890'
        with self.assertRaises(HostError):validate_receipt(r,self.req)

    def test_strict_json(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'\xff', b'{"x":"\\ud800"}', b' '*65537):
            with self.subTest(raw=raw[:20]), self.assertRaises(HostError): decode(raw)

    def test_url_rejections(self):
        for url in ['http://search.bilibili.com/all?keyword=hello+world','https://user@search.bilibili.com/all?keyword=hello+world','https://search.bilibili.com:443/all?keyword=hello+world','https://search.bilibili.com/all?keyword=hello+world&keyword=hello+world','https://search.bilibili.com/all?keyword=hello+world&redirect=https://evil.com','https://search.bilibili.com/all?keyword=other']:
            with self.subTest(url=url),self.assertRaises(HostError):search_url(url,'hello world')

    def test_symlink_spool(self):
        link=Path(self.temp.name)/'link';link.symlink_to(self.host.root)
        with self.assertRaisesRegex(HostError,'unsafe_spool'):FileBrowserHost(link)

    def test_dead_owner_not_replayed(self):
        state = dict(active=True, claimed=False,pid=999999999,owner='bad',issued_at=time.time()-1,expires_at=time.time()+20,cooldown=1)
        with self.host._locked():self.host._write('state.json',state)
        with self.assertRaisesRegex(HostError,'owner_gone'):self.host.claim()
        self.assertFalse(self.host._read('state.json')['active'])
        self.assertEqual(self.host._read('state.json')['status'],'unknown')

if __name__ == '__main__':unittest.main()
