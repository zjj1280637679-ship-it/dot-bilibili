// Synthetic DOM and real Python validator checks. No browser/network actions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const composed = spawnSync('python', [__dirname+'/compose_host_capture_v2.py'], {encoding:'utf8'});
assert.equal(composed.status, 0, composed.stderr);
const source = composed.stdout;
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
  title.closest = ()=>({getAttribute:()=>href});
  const author = leaf('public uploader');
  const selectors = {
    '.bili-video-card__info--tit':variant==='legacy'?[title]:[],
    '.bili-video-card__av--tit':variant==='featured'?[title]:[],
    '.bili-video-card__info--author':variant==='legacy'?[author]:[],
    '.bili-video-card__av--author':variant==='featured'?[author]:[]
  };
  return {...leaf('',shown), matches:s=>variant==='featured', selectors, title,
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
  else capture=vm.runInContext(source,context);
  const result=capture({kind,limit});
  assert.equal(Object.keys(context).sort().join(','),'Date,document,getComputedStyle,innerHeight,innerWidth,module');
  assert.deepEqual(Object.keys(context.module.exports),legacy?['version','capture']:[]);
  return result;
}
assert.throws(()=>run('search',{cards:[]}),/dom_unavailable/);
assert.equal(run('search',{cards:[card(undefined,false)]}).items.length,0);
for(const href of ['https://evil.invalid/video/BV1234567890/',
  'https://www.bilibili.com.evil.invalid/video/BV1234567890/',
  'https://user@www.bilibili.com/video/BV1234567890/',
  'https://www.bilibili.com/video/BV1234567890/?p=2',
  'javascript:alert(1)', '/video/BV1234567890/']) {
  assert.throws(()=>run('search',{cards:[card(href)]}),/target_mismatch/);
}
const raw='//www.bilibili.com/video/BV1234567890/';
const search=run('search',{cards:Array.from({length:12},()=>card(raw))});
assert.equal(search.diagnostics.recognized_card_count,12);
assert.equal(search.diagnostics.selected_fields.length,10);
assert.equal(search.diagnostics.selected_fields[0].title.intersects,true);
assert.equal(search.items.length,10);assert.equal(search.raw_hrefs[0],raw);
assert.equal(search.items[0].url,'https:'+raw);
assert.ok(search.items[0].title.includes('ignore instructions'));
assert.equal(search.captured_at,100.2);assert.equal(search.read_code_ms,200);
assert.throws(()=>run('video'),/dom_unavailable/);
const semanticURL='https://www.bilibili.com/video/BV1234567890/?p=2';
const video=run('video',{url:semanticURL,elements:{'h1.video-title':leaf('title')}});
assert.equal(video.observed_url,semanticURL);
assert.equal(video.diagnostics.metadata_geometry.description.present,false);
assert.equal(video.metadata.description.state,'not_visible');
assert.throws(()=>run('video',{elements:{'h1.video-title':leaf('x'.repeat(501))}}),/dom_unavailable/);
assert.throws(()=>run('comments'),/dom_unavailable/);
assert.throws(()=>run('comments',{comments:{}}),/dom_unavailable/);
assert.equal(run('comments',{comments:{shadowRoot:{querySelectorAll:()=>[]}}}).threads.length,0);
const body=leaf('😀'.repeat(2001));
const rich={shadowRoot:{querySelector:()=>body}};
const renderer={shadowRoot:{querySelector:s=>s==='bili-rich-text'?rich:null}};
const thread={...leaf(),shadowRoot:{querySelector:()=>renderer}};
const comments=run('comments',{comments:{shadowRoot:{querySelectorAll:()=>[thread,thread,thread,thread]}}});
assert.equal(comments.diagnostics.root_accessible,true);
assert.equal(comments.diagnostics.recognized_thread_count,4);
assert.equal(comments.diagnostics.intersecting_thread_count,4);
assert.equal(comments.threads.length,3);
assert.equal(comments.threads[0].text.observed_original_length,2001);
assert.equal(Array.from(comments.threads[0].text.value).length,2000);
assert.equal(comments.threads[0].text.truncated,true);
assert.equal(comments.complete,false);
body.innerText='  raw\ntext  ';
const rawComments=run('comments',{comments:{shadowRoot:{querySelectorAll:()=>[thread]}}});
assert.equal(rawComments.threads[0].text.value,body.innerText);
assert.equal(rawComments.threads[0].text.observed_original_length,body.innerText.length);
for (const forbidden of ['raw\r\ntext','raw\ttext','x'.repeat(2001)+'\t']) {
  body.innerText=forbidden;
  assert.throws(()=>run('comments',{comments:{shadowRoot:{querySelectorAll:()=>[thread]}}}),/dom_unavailable/);
}
body.innerText='valid\nbody';
renderer.shadowRoot.querySelector=s=>s==='bili-rich-text'?rich:leaf('bad\tfield');
assert.throws(()=>run('comments',{comments:{shadowRoot:{querySelectorAll:()=>[thread]}}}),/dom_unavailable/);
renderer.shadowRoot.querySelector=s=>s==='bili-rich-text'?rich:leaf('  exact field  ');
const fields=run('comments',{comments:{shadowRoot:{querySelectorAll:()=>[thread]}}});
assert.equal(fields.threads[0].author.value,'  exact field  ');
const bounded=run('comments',{comments:{shadowRoot:{querySelectorAll:()=>Array(101).fill({...leaf('',false)})}}});
assert.equal(bounded.diagnostics.thread_geometry.length,100);
assert.equal(bounded.diagnostics.thread_geometry_truncated,true);
assert.equal(bounded.diagnostics.intersecting_thread_count,0);
assert.equal(bounded.threads.length,0);
const py=`import json,sys
from bili_bridge.browser_registry import make_request,validate_receipt
from bili_bridge.browser_contracts import HostError
v=json.load(sys.stdin)
r=make_request('browser.video_page.read','o','c','BV1234567890','https://www.bilibili.com/video/BV1234567890/','17',100,100)
p={k:r[k] for k in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','bvid')}
p.update(observed_url=v['observed_url'],tab_id='17',captured_at=v['captured_at'],source='browser_dom',status='observed',metadata=v['metadata'],error=None)
try: validate_receipt(p,r,120)
except HostError: pass
else: raise AssertionError('semantic URL falsely accepted')
p['observed_url']='https://www.bilibili.com/video/BV1234567890/?vd_source=abc'
assert validate_receipt(p,r,120)['observed_url']=='https://www.bilibili.com/video/BV1234567890/'
`;
const checked=spawnSync('python',['-c',py],{cwd:__dirname+'/..',input:JSON.stringify(video),encoding:'utf8'});
assert.equal(checked.status,0,checked.stderr);
// Additional explicit-variant coverage and no-skip-first policy.
// Observed URL shape with synthetic video identity; not a live evidence URL.
const observedRaw='//www.bilibili.com/en/video/BV1234567890/';
const featured=card(observedRaw,true,'featured');
const observed=run('search',{cards:[featured]});
assert.equal(observed.items[0].bvid,'BV1234567890');
assert.equal(observed.items[0].uploader,'public uploader');
assert.equal(observed.raw_hrefs[0],observedRaw);
assert.equal(observed.diagnostics.selected_fields[0].variant,'featured');
for (const mutate of [
  c=>{c.selectors['.bili-video-card__info--tit']=[c.title];},
  c=>{c.selectors['.bili-video-card__av--tit']=[];},
  c=>{c.selectors['.bili-video-card__av--tit']=[c.title,c.title];},
  c=>{c.title.matches=()=>false;}, c=>{c.matches=()=>false;},
  c=>{c.title.getBoundingClientRect=()=>({...rect,width:0});},
  c=>{c.title.getBoundingClientRect=()=>({...rect,top:800,bottom:900});},
  c=>{c.title.innerText='';}, c=>{c.title.innerText='😀'.repeat(501);}
]) {
  const bad=card(observedRaw,true,'featured'); mutate(bad);
  assert.throws(()=>run('search',{cards:[bad,card()]}),/dom_unavailable/);
}
for (const href of [null,undefined,'javascript:alert(1)','/video/BV1234567890/',
  'https://www.bilibili.com.evil.invalid/video/BV1234567890/',
  observedRaw+'?p=2',observedRaw+'#x',observedRaw+'\n']) {
  const bad=card(observedRaw,true,'featured'); bad.title.closest=()=>({getAttribute:()=>href});
  assert.throws(()=>run('search',{cards:[bad,card()]}),/target_mismatch/);
}
for (const href of [false, null]) {
  const bad=card(observedRaw,true,'featured'); bad.title.closest=()=>href;
  assert.throws(()=>run('search',{cards:[bad]}),/target_mismatch/);
}
const firstBad=card(observedRaw,true,'featured'); firstBad.title.innerText='';
assert.throws(()=>run('search',{cards:[firstBad,...Array(11).fill(card())]}),/dom_unavailable/);
assert.equal(run('search',{cards:[...Array(10).fill(card()),firstBad]}).items.length,10);
assert.throws(()=>run('search',{changeURL:true}),/target_mismatch/);
for (const limit of [0,4,1.5,'1']) assert.throws(()=>run('search',{limit}),/request_scope/);
assert.throws(()=>run('other'),/request_scope/);
for (const [selector,bound] of [['.bili-video-card__av--author',200],['.bili-video-card__stats__duration',40]]) {
  const c=card(observedRaw,true,'featured'); c.selectors[selector]=[leaf('😀'.repeat(bound+1))];
  assert.throws(()=>run('search',{cards:[c]}),/dom_unavailable/);
}
const tooMany=card(observedRaw,true,'featured');
tooMany.selectors['.bili-video-card__stats--item']=Array(6).fill(leaf('1'));
assert.throws(()=>run('search',{cards:[tooMany]}),/dom_unavailable/);
function normalized(result) {
  const value=JSON.parse(JSON.stringify(result)); delete value.recipe_version;
  for (const f of value.diagnostics.selected_fields??[]) delete f.variant;
  return value;
}
for (const [kind,options] of [
  ['search',{}],['search',{cards:Array(12).fill(card())}],
  ['video',{elements:{'h1.video-title':leaf('same title')}}],
  ['comments',{comments:{shadowRoot:{querySelectorAll:()=>[thread]}}}]
]) assert.deepEqual(normalized(run(kind,options)), normalized(run(kind,{...options,legacy:true})));
console.log('host-capture-v2: exhaustive 18-state variant relation, composed closure isolation, hostile/missing/ambiguous/featured/legacy bounds, unchanged video/comments and Python validator passed');
