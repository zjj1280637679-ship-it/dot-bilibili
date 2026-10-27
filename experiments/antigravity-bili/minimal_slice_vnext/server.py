"""MCP stdio server pinned to protocol 2025-06-18; fixture only, no network."""
import argparse
import json
import sys
from .service import Service

VERSION = '2025-06-18'
MAX_LINE = 32768
SCHEMAS = {
 'capabilities.list': {},
 'video.reference.resolve': {'value': {'type':'string','maxLength':2048}},
 'video.metadata.read': {k:{'type':'string'} for k in ('reference_id','expected_bvid','operation_id','backend')},
 'operation.status': {'operation_id': {'type':'string','maxLength':128}},
}
SCHEMAS['video.metadata.read']['backend']={'type':'string','enum':['fixture']}

def pairs(items):
    d={}
    for k,v in items:
        if k in d: raise ValueError('duplicate_key')
        d[k]=v
    return d

def error(id, code, message):
    return {'jsonrpc':'2.0','id':id,'error':{'code':code,'message':message}}

class Protocol:
    def __init__(self, service):
        self.service=service
        self.initialized=False
        self.ready=False

    def receive(self, raw):
        try:
            obj=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except Exception:
            return error(None,-32700,'Parse error')
        if not isinstance(obj,dict) or obj.get('jsonrpc')!='2.0' or not isinstance(obj.get('method'),str):
            return error(None,-32600,'Invalid Request')
        id=obj.get('id'); method=obj['method']; params=obj.get('params',{})
        if 'id' in obj and (type(id) not in (int,str) or (isinstance(id,str) and len(id)>128)):
            return error(None,-32600,'Invalid request ID')
        if not isinstance(params,dict):
            return error(id,-32602,'Invalid params') if 'id' in obj else None
        if 'id' not in obj:
            if method=='notifications/initialized' and self.initialized: self.ready=True
            return None
        if method=='initialize':
            if self.initialized: return error(id,-32600,'Already initialized')
            if not isinstance(params.get('protocolVersion'),str): return error(id,-32602,'Missing protocolVersion')
            self.initialized=True
            result={'protocolVersion':VERSION,'capabilities':{'tools':{}},
                    'serverInfo':{'name':'bili-offline-fixture-slice','version':'0.1.1-candidate'}}
        elif method=='ping': result={}
        elif not self.ready: return error(id,-32000,'Initialization required')
        elif method=='tools/list':
            result={'tools':[{'name':name,'description':('Offline fixture only. Metadata requires a process-local reference_id from video.reference.resolve, not a search; only BV17x411w7KC has fixture data. No real Bilibili access.'),
              'inputSchema':{'type':'object','properties':schema,'required':list(schema),'additionalProperties':False}}
              for name,schema in SCHEMAS.items()]}
        elif method=='tools/call':
            if (not isinstance(params.get('name'),str) or
                not set(params).issubset({'name','arguments','_meta'}) or
                not isinstance(params.get('arguments',{}),dict) or
                ('_meta' in params and not isinstance(params['_meta'],dict))):
                return error(id,-32602,'Invalid tool call')
            out=self.service.call(params['name'],params.get('arguments',{}))
            result={'content':[{'type':'text','text':json.dumps(out,ensure_ascii=True,allow_nan=False)}],
                    'structuredContent':out,'isError':out['status'] not in ('completed','pending')}
        else: return error(id,-32601,'Method not found')
        return {'jsonrpc':'2.0','id':id,'result':result}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True)
    p.add_argument('--fixture-ready',action='store_true',help='Only initializes a NEW fixture DB unpaused; never clears existing pause')
    a=p.parse_args()
    protocol=Protocol(Service(a.db, initial_paused=not a.fixture_ready))
    while True:
        line=sys.stdin.buffer.readline(MAX_LINE+1)
        if not line: break
        if len(line)>MAX_LINE:
            # Drain only this oversized frame, do not parse its tail as another request.
            while line and not line.endswith(b'\n'): line=sys.stdin.buffer.readline(MAX_LINE+1)
            out=error(None,-32700,'Frame too large')
        else: out=protocol.receive(line)
        if out is not None:
            sys.stdout.write(json.dumps(out,ensure_ascii=True,allow_nan=False)+'\n');sys.stdout.flush()

if __name__=='__main__': main()
