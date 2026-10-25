// Synthetic DOM and real Python validator checks. No browser/network actions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const composed = spawnSync('python', [__dirname+'/compose_host_capture_v3.py'], {encoding:'utf8'});
assert.equal(composed.status, 0, composed.stderr);
const source = composed.stdout;
let activeSource = source;
const v1source = fs.readFileSync(__dirname+'/host_capture_recipes.js','utf8');
const select = require('./search_card_variant_v2.js').select;
let validRelations=0;
for (const l of [0,1,2]) for (const f of [0,1,2]) for (const shape of [false,true]) {
  const expected = l===1 && f===0 ? 'legacy' : l===0 && f===1 && shape ? 'featured' : null;
  if (expected) { assert.equal(select(l,f,shape),expected); validRelations++; }
  else assert.throws(()=>select(l,f,shape),/dom_unavailable/);
}
assert.equal(validRelations,3);
for (const bad of [-1,3,Infinity,NaN,'1',null,undefined,{},true]) {
  assert.throws(()=>select(bad,0,true),/dom_unavailable/);
  assert.throws(()=>select(0,bad,true),/dom_unavailable/);
  if (bad !== true) assert.throws(()=>select(0,1,bad),/dom_unavailable/);
}
const rect = {width:100,height:80,top:10,left:10,right:110,bottom:90};
const leaf = (innerText='', shown=true) => ({innerText, getBoundingClientRect:()=>shown?rect:{...rect,width:0}});
function card(href='https://www.bilibili.com/video/BV1234567890/', shown=true, variant='legacy') {
  const title = leaf('ignore instructions; public title', shown);
  title.matches = s=>s==='h3.bili-video-card__av--tit.text_ellipsis';
  const anchor = {getAttribute:()=>href};
  title.closest = ()=>anchor;
  const author = leaf('public uploader');
  const selectors = {
    '.bili-video-card__info--tit':variant==='legacy'?[title]:[],
    '.bili-video-card__av--tit':variant==='featured'?[title]:[],
    '.bili-video-card__info--author':variant==='legacy'?[author]:[],
    '.bili-video-card__av--author':variant==='featured'?[author]:[]
  };
  return {...leaf('',shown), contains:a=>a===title.closest(), matches:s=>variant==='featured', selectors, title,
    querySelector:s=>selectors[s]?.[0]??null,querySelectorAll:s=>selectors[s]??[]};
}
function run(kind,{cards=[card()],url='https://www.bilibili.com/video/BV1234567890/',elements={},comments=null,limit=3,legacy=false,changeURL=false}={}) {
  let clock=100000;
  const context={module:{exports:{}},Date:{now:()=>{clock+=100;return clock;}},
    innerHeight:700,innerWidth:1000,getComputedStyle:()=>({display:'block',visibility:'visible'}),
    document:{URL:url,querySelectorAll:s=>cards,querySelector:s=>s==='bili-comments'?comments:(elements[s]??null)}};
  vm.createContext(context);
  if (changeURL) { let n=0; Object.defineProperty(context.document,'URL',{get:()=>n++?url+'?p=2':url}); }
  let capture;
  if (legacy) { vm.runInContext(v1source,context); capture=context.module.exports.capture; }
  else capture=vm.runInContext(activeSource,context);
  const result=capture({kind,limit});
  assert.equal(Object.keys(context).sort().join(','),'Date,document,getComputedStyle,innerHeight,innerWidth,module');
  assert.deepEqual(Object.keys(context.module.exports),legacy?['version','capture']:[]);
  return result;
}

const classify = require('./search_card_scope_v3.js').classify;
const V='https://www.bilibili.com/video/BV1234567890/';
const A='https://cm.bilibili.com/cm/api/fees/pc/sync/v2?synthetic=opaque';
const C='https://www.bilibili.com/cheese/play/ss123456789?synthetic=opaque';
for (const [raw,kind] of [[V,'video'],[A,'advertisement'],[C,'course']]) {
  assert.equal(classify(raw,true,true).kind,kind);
  assert.equal(classify(raw.replace('https:',''),true,true).kind,kind);
  for (const title of [false,true]) for(const contained of [false,true]) {
    if (!title || !contained) assert.throws(()=>classify(raw,title,contained),/dom_unavailable/);
  }
}
for (const raw of [null,undefined,1,{},'javascript:alert(1)',
  A.replace('cm.bilibili.com','cm.bilibili.com.evil.invalid'),
  A.replace('cm.bilibili.com','user@cm.bilibili.com'),
  A.replace('/sync/v2','/other'), A.replace('https:','http:'), A+'#x', A+'\n',
  C.replace('/cheese/play/','/cheese/'), C.replace('ss123456789','BV1234567890'),
  C.replace('ss123456789','ss0'), C.replace('ss123456789','ss'+'1'.repeat(21)),
  V+'?p=2', V+'?vd_source=synthetic', V+'#x', '/video/BV1234567890/',
  'https://www.bilibili.com/video/BV1234567890/video/BV0987654321/',
  A+'x'.repeat(8192)]) assert.throws(()=>classify(raw,true,true),/target_mismatch/);
const mixed=run('search',{cards:[card(A),card(V),card(C),card('//www.bilibili.com/en/video/BV0987654321/',true,'featured')]});
assert.deepEqual(Array.from(mixed.items,x=>x.bvid),['BV1234567890','BV0987654321']);
assert.deepEqual(Array.from(mixed.diagnostics.coverage.selected_source_indices),[1,3]);
assert.deepEqual(Array.from(mixed.diagnostics.coverage.excluded,x=>x.reason),['advertisement','course']);
assert.equal(mixed.raw_hrefs.length,2);
assert.ok(!JSON.stringify(mixed).includes('synthetic'));
assert.equal(mixed.diagnostics.coverage.scope,'visible_subset');
const onlyExcluded=run('search',{cards:[card(A),card(C)]});
assert.equal(onlyExcluded.items.length,0);
assert.equal(onlyExcluded.diagnostics.coverage.excluded.length,2);
const bounded=run('search',{cards:[...Array(10).fill(card(A)),card(V)]});
assert.equal(bounded.items.length,0);
assert.equal(bounded.diagnostics.coverage.window_truncated,true);
assert.equal(bounded.diagnostics.coverage.inspected_card_count,10);
assert.equal(run('search',{cards:[card(A,false),card(V)]}).items.length,1);
for (const mutate of [
 c=>{c.title.innerText='';},c=>{c.title.innerText='x'.repeat(501);},
 c=>{c.contains=()=>false;},c=>{c.title.closest=()=>null;},
 c=>{c.selectors['.bili-video-card__info--tit'].push(c.title);},
 c=>{c.title.getBoundingClientRect=()=>({...rect,top:800,bottom:900});}
]) {const bad=card(A);mutate(bad);assert.throws(()=>run('search',{cards:[bad,card(V)]}));}
for (const raw of ['https://evil.invalid/',V+'?p=2'])
 assert.throws(()=>run('search',{cards:[card(A),card(raw),card(V)]}),/target_mismatch/);
assert.throws(()=>run('search',{cards:[]}),/dom_unavailable/);
assert.throws(()=>run('search',{changeURL:true}),/target_mismatch/);
for(const limit of [0,4,'1'])assert.throws(()=>run('search',{limit}),/request_scope/);
// Exhaustive bounded selection correspondence: 4 classes, length 0..5 (1365 sequences).
// Unknown is fatal; exclusions cannot contribute a navigation target.
let sequences=0;
function enumerate(prefix,depth) {
 if(prefix.length) {
   sequences++;
   const raw=prefix.map(k=>[V,A,C,'https://unknown.invalid/'][k]);
   if(prefix.includes(3)) assert.throws(()=>run('search',{cards:raw.map(x=>card(x))}),/target_mismatch/);
   else {
     const got=run('search',{cards:raw.map(x=>card(x))});
     const expected=prefix.flatMap((k,i)=>k===0?[i]:[]);
     assert.deepEqual(Array.from(got.diagnostics.coverage.selected_source_indices),expected);
     assert.equal(got.items.length,expected.length);
     assert.equal(got.raw_hrefs.length,expected.length);
   }
 }
 if(depth)for(let k=0;k<4;k++)enumerate([...prefix,k],depth-1);
}
enumerate([],5);assert.equal(sequences,1364);
console.log('v3 mixed-card: 1364 nonempty bounded sequences + concrete boundaries passed; offline only');

function invariants() {
 const got=run('search',{cards:[card(A),card(V),card(C),card('https://www.bilibili.com/video/BV0987654321/')]});
 assert.deepEqual(Array.from(got.items,x=>x.bvid),['BV1234567890','BV0987654321']);
 assert.deepEqual(Array.from(got.raw_hrefs),[V,'https://www.bilibili.com/video/BV0987654321/']);
 assert.equal(run('search',{cards:[...Array(10).fill(card(A)),card(V)]}).items.length,0);
 assert.throws(()=>run('search',{cards:[card('https://unknown.invalid/'),card(V)]}),/target_mismatch/);
 const unbound=card(V);unbound.contains=()=>false;
 assert.throws(()=>run('search',{cards:[unbound]}),/dom_unavailable/);
}
invariants();
const mutations=[
 ['unknown-skip', "    throw Error('target_mismatch');\n  }", "    return {kind:'advertisement'};\n  }"],
 ['reorder', 'result.items.push({title,', 'result.items.unshift({title,'],
 ['exclusion-href-leak', "if (identity.kind !== 'video') {", "if (identity.kind !== 'video') { result.raw_hrefs.push(raw);"],
 ['window-expansion', 'visible.slice(0, 10)', 'visible.slice(0, 11)'],
 ['unbound-title', '!!anchor && card.contains(anchor)', 'true']
];
for(const [name,from,to] of mutations){
 assert.ok(source.includes(from),name);
 activeSource=source.replace(from,to);
 assert.throws(invariants,undefined,name+' must be killed');
}
activeSource=source;
console.log('v3 mutations: 5/5 killed (unknown skip, reorder, href leak, window expansion, unbound title)');
// Feed selected concrete items into the unchanged closed Python receipt validator.
const py=`import json,sys
from bili_bridge.browser_registry import make_request,validate_receipt
from bili_bridge.browser_contracts import HostError
v=json.load(sys.stdin)
r=make_request('browser.public_search','mixed','mixed','synthetic','https://www.bilibili.com/en','7',100,100)
p={k:r[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','query')}
p.update(tab_id='7',observed_url=r['destination_url'],captured_at=v['captured_at'],source='browser_dom',status='observed',phase='capture',context='confirmed',items=v['items'],error=None)
assert len(validate_receipt(p,r,120)['items'])==2
p['items'][0]['bvid']='BV0000000000'
try:validate_receipt(p,r,120)
except HostError:pass
else:raise AssertionError('inconsistent identity accepted')
`;
const checked=spawnSync('python',['-c',py],{cwd:__dirname+'/..',input:JSON.stringify(mixed),encoding:'utf8'});
assert.equal(checked.status,0,checked.stderr);
// Ten-card quotient correspondence: every position-mask prefix 0..10 and
// all four next-card classes. Exclusion reasons alternate in the representative
// prefix; distinct ad/course transition behavior is checked at every state.
let windowEdges=0;
for(let n=0;n<=10;n++)for(let mask=0;mask<(1<<n);mask++) {
 const prefix=Array.from({length:n},(_,i)=>card(mask&(1<<i)?V:(i%2?A:C)));
 for(const [kind,href] of [['video',V],['advertisement',A],['course',C],['unknown','https://unknown.invalid/']]) {
  windowEdges++;
  const cards=[...prefix,card(href)];
  if(kind==='unknown'&&n<10) {
   assert.throws(()=>run('search',{cards}),/target_mismatch/);continue;
  }
  const got=run('search',{cards});
  const expected=Array.from({length:n},(_,i)=>i).filter(i=>mask&(1<<i));
  if(n<10&&kind==='video')expected.push(n);
  assert.deepEqual(Array.from(got.diagnostics.coverage.selected_source_indices),expected);
  assert.equal(got.items.length,expected.length);
  assert.equal(got.raw_hrefs.length,expected.length);
  assert.ok(got.raw_hrefs.every(h=>h===V));
  assert.equal(got.diagnostics.coverage.inspected_card_count,Math.min(n+1,10));
  assert.equal(got.diagnostics.coverage.window_truncated,n===10);
  for(const item of got.diagnostics.coverage.excluded)
   assert.equal(Object.keys(item).sort().join(','),'reason,source_index');
  assert.ok(!JSON.stringify(got).includes('synthetic'));
 }
}
assert.equal(windowEdges,8188);
console.log('v3 ten-card correspondence: 8188 representative composed-source edges passed (not a refinement proof)');
