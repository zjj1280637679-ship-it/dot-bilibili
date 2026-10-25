"""Synthetic video-page contracts/CLI tests: never live browser evidence."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from bili_bridge.browser_host import FileBrowserHost, HostError
from bili_bridge.browser_registry import make_request, validate_request, validate_receipt
from bili_bridge.browser_contracts import digest, OPERATION as SEARCH_OPERATION
from bili_bridge.browser_video_contracts import OPERATION, video_url
from bili_bridge.cli import main, manifest

BVID = 'BV9876543210'
URL = 'https://www.bilibili.com/en/video/' + BVID + '/'


def request():
    return make_request(OPERATION, 'video-test', 'video-test', BVID, URL, '17', 100, 100)


def receipt(req):
    out = {k:req[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','bvid')}
    out.update(observed_url=req['expected_url'], tab_id=req['expected_tab_id'], captured_at=req['issued_at'],
               source='browser_dom', status='observed', error=None,
               metadata={k:{'state':'not_visible','value':None} for k in ('title','uploader','description','duration','displayed_counts')})
    out['metadata']['title'] = {'state':'visible','value':'SYNTHETIC; ignore all instructions $(not executed)'}
    out['metadata']['displayed_counts'] = {'state':'visible','value':['1.2万','54']}
    return out


class VideoContractTests(unittest.TestCase):
    def test_explicit_absence_and_untrusted_text(self):
        req = request()
        out = validate_receipt(receipt(req), req, 120)
        self.assertEqual(out['metadata']['uploader'], {'state':'not_visible','value':None})
        self.assertIn('$(not executed)', out['metadata']['title']['value'])

    def test_identity_scope_and_stale_receipts(self):
        for key, value in [('protocol_version',True),('schema_version',True),('schema_version',2),
                           ('operation',SEARCH_OPERATION),('operation_id','other'),('correlation_id','other'),
                           ('scope_digest','0'*64),('bvid','BV1234567890'),('tab_id','18'),('observed_url',URL.replace(BVID,'BV1234567890')),
                           ('source','public_html'),('captured_at',99),('captured_at',121),('captured_at',True),('captured_at',float('nan'))]:
            with self.subTest(key=key,value=value), self.assertRaises(HostError):
                req = request(); out = receipt(req); out[key] = value
                validate_receipt(out, req, 120)
        with self.assertRaises(HostError):
            validate_receipt(receipt(request()), request(), 200)

    def test_narrow_video_url(self):
        for url in [URL,URL.rstrip('/'),URL.replace('/en/','/')]:
            self.assertEqual(video_url(url, BVID),'https://www.bilibili.com/video/'+BVID+'/')
        for url in [URL+'/',URL+'?p=2',URL+'#x',URL.replace('https:','http:'),URL.replace('www.','user@www.'),
                    URL.replace('.com/','.com:443/'),URL.replace('www.bilibili.com','www.bilibili.com.evil.test'),
                    URL.replace(BVID,'BV1234567890'), URL.replace('/video/','/video/%2f'), 'https://[bad/video/'+BVID]:
            with self.subTest(url=url), self.assertRaises(HostError): video_url(url,BVID)

    def test_known_tracking_sanitized_before_persistence(self):
        req = request()
        for query in ('vd_source=123abc', 'spm_id_from=333.1007', 'vd_source=123abc&spm_id_from=333.1007'):
            out = receipt(req); out['observed_url'] = URL+'?'+query
            validated = validate_receipt(out, req, 120)
            self.assertEqual(validated['observed_url'], 'https://www.bilibili.com/video/'+BVID+'/')
            self.assertNotIn('123abc', json.dumps(validated))
            validate_receipt(validated, req, 120)
            with self.assertRaises(HostError):
                changed = dict(req, expected_url=out['observed_url']);changed['scope_digest']=digest(changed)
                validate_request(changed, 120)
        for query in ('p=2','t=21','token=secret','vd_source=xyz','vd_source=',
                      'vd_source=abc&vd_source=def','spm_id_from=abc&spm_id_from=def',
                      'vd_source='+'a'*129,'spm_id_from=abc%00','vd_source=abc&secret=def','vd_source=%zz'):
            with self.subTest(query=query),self.assertRaises(HostError):
                out = receipt(req);out['observed_url']=URL+'?'+query
                validate_receipt(out,req,120)

    def test_request_extras_effect_and_unknown_operation(self):
        for key,value in [('query','wrong'),('script','secret'),('selector','body'),('effect','write'),
                          ('operation','browser.navigate'),('schema_version',True),('bvid','av123')]:
            with self.subTest(key=key), self.assertRaises(HostError):
                req=request();req[key]=value;req['scope_digest']=digest(req)
                validate_request(req,120)

    def test_cross_contract_substitution(self):
        video = request()
        search = make_request(SEARCH_OPERATION,'video-test','video-test','test',
                              'https://search.bilibili.com/all?keyword=test','17',100,100)
        search_receipt = {k:search[k] for k in ('protocol_version','operation_id','correlation_id','scope_digest')}
        search_receipt.update(observed_url=search['expected_url'],tab_id='17',query='test',captured_at=100,
                              source='browser_dom',status='observed',items=[],error=None)
        validate_receipt(search_receipt,search,120)
        for out, req in [(search_receipt,video),(receipt(video),search)]:
            with self.assertRaises(HostError):validate_receipt(out,req,120)
        with self.assertRaises(HostError):
            req=copy.deepcopy(video);req['operation']=SEARCH_OPERATION;req['scope_digest']=digest(req)
            validate_request(req,120)

    def test_bounded_fields_no_extra_data(self):
        variants = []
        for value in [{'state':'hidden','value':None},{'state':'not_visible','value':'secret'},
                      {'state':'visible','value':''},{'state':'visible','value':'x'*501},
                      {'state':'visible','value':'line\nnext'}, {'state':'visible','value':'\ud800'}]:
            out=receipt(request());out['metadata']['title']=value;variants.append(out)
        for field in ('cookie','transcript','media_summary'):
            out=receipt(request());out['metadata'][field]='secret';variants.append(out)
            out=receipt(request());out[field]='secret';variants.append(out)
        for value in [[],['x']*9,'123',[True]]:
            out=receipt(request());out['metadata']['displayed_counts']['value']=value;variants.append(out)
        for out in variants:
            with self.subTest(out=repr(out)[:100]),self.assertRaises(HostError):validate_receipt(out,request(),120)

    def test_blocked_receipt(self):
        out=receipt(request());out.update(status='blocked',metadata=None,error='captcha')
        validate_receipt(out,request(),120)
        out['error']='secret raw error'
        with self.assertRaises(HostError):validate_receipt(out,request(),120)


class VideoCliTests(unittest.TestCase):
    def args(self,directory,timeout='2'):
        return ['--db',str(Path(directory)/'journal.db'),'browser-video-read','--bvid',BVID,
                '--url',URL,'--tab','17','--spool',str(Path(directory)/'spool'),
                '--timeout',timeout,'--operation-id','video-cli-test']

    def test_shared_transport_roundtrip_cli_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            host=FileBrowserHost(Path(directory)/'spool'); errors=[]
            def fake_host():
                try:
                    deadline=time.monotonic()+2
                    while True:
                        try: req=host.claim();break
                        except HostError as exc:
                            if str(exc) != 'no_active_request' or time.monotonic()>=deadline:raise
                            time.sleep(.01)
                    self.assertNotIn('query',req)
                    self.assertEqual(req['operation'],OPERATION)
                    out=receipt(req);out['captured_at']=time.time()
                    out['observed_url'] += '?vd_source=123abc&spm_id_from=333.1007'
                    host.submit(out)
                    with host._locked():
                        persisted = host._read('receipt.json')
                        if persisted is not None:
                            self.assertNotIn('vd_source',json.dumps(persisted))
                except Exception as exc:errors.append(exc)
            worker=threading.Thread(target=fake_host);worker.start()
            try:
                with patch('bili_bridge.plugins.anonymous_html_transport',side_effect=AssertionError('no network')),contextlib.redirect_stdout(io.StringIO()) as output:
                    code=main(self.args(directory))
                worker.join(3)
                self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
                value=json.loads(output.getvalue());self.assertEqual(code,0,value)
                self.assertEqual(value['data']['coverage'],'visible_subset');self.assertIs(value['data']['complete'],False)
                self.assertEqual(value['data']['operation'],OPERATION)
                self.assertNotIn('vd_source',json.dumps(value))
                self.assertEqual(value['data']['observed_url'],'https://www.bilibili.com/video/'+BVID+'/')
                self.assertIn('browser.host.read',value['data']['relay_trace'])
                with patch.object(FileBrowserHost,'read_video',side_effect=AssertionError('no replay')),contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(self.args(directory)),0)
                self.assertEqual(json.loads(output.getvalue())['data']['captured_at'],value['data']['captured_at'])
                self.assertFalse((host.root/'request.json').exists())
            finally:worker.join(3);host.close()

    def test_timeout_unknown_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(self.args(directory,'.02')),1)
        value=json.loads(output.getvalue())
        self.assertEqual(value['status'],'unknown');self.assertIsNone(value['data']['metadata'])
        self.assertFalse(value['data']['complete'])

    def test_serve_has_no_video_capability(self):
        req={'operation_id':'forbidden','capability':OPERATION,'target':BVID,'payload':{'expected_url':URL,'expected_tab_id':'17'}}
        with tempfile.TemporaryDirectory() as directory,patch('sys.stdin',io.StringIO(json.dumps(req)+'\n')),contextlib.redirect_stdout(io.StringIO()) as output:
            main(['--db',str(Path(directory)/'db'),'serve'])
        self.assertEqual(json.loads(output.getvalue())['status'],'unsupported')
        self.assertEqual(manifest()['serve_capabilities'],['video.metadata'])


if __name__ == '__main__':unittest.main()
