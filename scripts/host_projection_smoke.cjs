// Offline synthetic smoke only; never controls a browser or loads page content.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(__dirname + '/host_projection_recipe.js', 'utf8');
const rect = {width:100,height:80,top:10,left:10,right:110,bottom:90};
function leaf(text, shown=true) {
  return {innerText:text,getBoundingClientRect:()=>shown?rect:{...rect,width:0}};
}
function card(index) {
  const title = leaf('Synthetic title ' + index);
  title.closest = () => ({getAttribute:()=>'https://www.bilibili.com/en/video/BV123456789'+index+'/'});
  const fields = {
    '.bili-video-card__info--tit':title,
    '.bili-video-card__info--author':leaf('Synthetic uploader'),
    '.bili-video-card__stats__duration':leaf('00:12',index!==2)
  };
  return {...leaf(''),querySelector:s=>fields[s]??null,
    querySelectorAll:s=>s==='.bili-video-card__stats--item'?[leaf('12',index!==2),leaf('0',index!==2)]:[]};
}
(async()=>{
  let calls=0;
  const context={
    Date,innerHeight:757,innerWidth:1180,
    getComputedStyle:()=>({display:'block',visibility:'visible'}),
    document:{URL:'https://search.bilibili.com/en/all?keyword=test',querySelectorAll:s=>{
      assert.equal(s,'.bili-video-card');
      return [card(0),card(1),card(2),card(3),card(4)];
    }},
    perfTab:{playwright:{evaluate:async fn=>{calls++;return fn();}}}
  };
  vm.createContext(context);
  await vm.runInContext('(async()=>{'+source+'; return hostProjection;})()',context).then(result=>{
    assert.equal(calls,1);
    assert.equal(result.items.length,4);
    assert.equal(result.items[0].title,'Synthetic title 0');
    assert.equal(result.items[2].duration,'');
    assert.equal(result.items[2].displayed_counts.length,0);
    assert.ok(result.captured_at > 0);
    assert.ok(result.read_code_ms >= 0);
  });
  console.log('Host-only fixed projection synthetic smoke passed (4-card cap, hidden fields, timestamp, one read)');
})().catch(error=>{console.error(error);process.exitCode=1;});

