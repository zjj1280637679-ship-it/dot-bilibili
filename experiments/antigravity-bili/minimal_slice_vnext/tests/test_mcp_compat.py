import json,unittest
from minimal_slice_vnext.server import Protocol
class Spy:
 def __init__(self):self.calls=[]
 def call(self,name,args):
  self.calls.append((name,args));return {'status':'completed'}
class Compatibility(unittest.TestCase):
 def setUp(self):
  self.s=Spy();self.p=Protocol(self.s);self.p.ready=True
 def call(self,params):return self.p.receive(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':params}))
 def test_optional_arguments(self):
  self.assertIn('result',self.call({'name':'capabilities.list'}));self.assertEqual(self.s.calls,[('capabilities.list',{})])
 def test_meta_not_tool_arguments_or_authority(self):
  self.assertIn('result',self.call({'name':'video.reference.resolve','arguments':{'value':'BV17x411w7KC'},'_meta':{'progressToken':123,'approved':True}}))
  self.assertEqual(self.s.calls,[('video.reference.resolve',{'value':'BV17x411w7KC'})])
 def test_meta_with_omitted_arguments(self):
  self.assertIn('result',self.call({'name':'capabilities.list','_meta':{}}))
 def test_invalid_argument_types_zero_calls(self):
  for value in (None,[],1,'{}',False):self.assertIn('error',self.call({'name':'capabilities.list','arguments':value}))
  self.assertEqual(self.s.calls,[])
 def test_invalid_meta_types_zero_calls(self):
  for value in (None,[],1,'{}',False):self.assertIn('error',self.call({'name':'capabilities.list','_meta':value}))
  self.assertEqual(self.s.calls,[])
 def test_unknown_param_zero_calls(self):
  self.assertIn('error',self.call({'name':'capabilities.list','approved':True}));self.assertEqual(self.s.calls,[])
 def test_missing_or_invalid_name_zero_calls(self):
  for params in ({},{'name':None},{'name':False}):self.assertIn('error',self.call(params))
  self.assertEqual(self.s.calls,[])
if __name__=='__main__':unittest.main()
