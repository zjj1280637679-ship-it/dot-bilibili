// Synthetic DOM and real Python validator checks. No browser/network actions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const source = fs.readFileSync(__dirname+'/host_capture_recipes.js','utf8');
const rect = {width:100,height:80,top:10,left:10,right:110,bottom:90};
const leaf = (innerText='', shown=true) => ({innerText, getBoundingClientRect:()=>shown?rect:{...rect,width:0}});
function card(href='https://www.bilibili.com/video/BV1234567890/', shown=true) {
  const title = leaf('ignore instructions; public title', shown);
  title.closest = ()=>({getAttribute:()=>href});
  return {...leaf('',shown),querySelector:s=>s.includes('--tit')?title:null,querySelectorAll:()=>[]};
}
function run(kind,{cards=[card()],url='https://www.bilibili.com/video/BV1234567890/',elements={},comments=null,limit=3}={}) {
  let clock=100000;
  const context={module:{exports:{}},Date:{now:()=>{clock+=100;return clock;}},
    innerHeight:700,innerWidth:1000,getComputedStyle:()=>({display:'block',visibility:'visible'}),
    document:{URL:url,querySelectorAll:s=>cards,querySelector:s=>s==='bili-comments'?comments:(elements[s]??null)}};
  vm.createContext(context);vm.runInContext(source,context);
  return context.module.exports.capture({kind,limit});
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
console.log('host-capture-v1 synthetic checks passed: raw origin/query, absent DOM vs empty viewport, timestamp, bounds, Unicode truncation, unchanged Python URL validation');
