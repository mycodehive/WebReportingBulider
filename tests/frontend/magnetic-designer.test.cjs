'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const test = require('node:test');
const {JSDOM} = require('jsdom');
const root=path.resolve(__dirname,'../..');
const rendered=spawnSync('uv',['run','python','tests/frontend/fixture.py','render'],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});
assert.equal(rendered.status,0,rendered.stderr);
const fixture=JSON.parse(rendered.stdout);

async function designer(t,flow=false){
 const dom=new JSDOM(fixture.html,{runScripts:'outside-only',url:'http://localhost/'});
 t.after(()=>dom.window.close());
 const w=dom.window,d=w.document,definition=structuredClone(fixture.report.definition),p=definition.pages[0];
 const element=(id,x,y)=>({element_id:id,type:'text',text:id,geometry:{x_mm:x,y_mm:y,width_mm:20,height_mm:10},style:{},overflow:'fixed_clip'});
 p.elements=[element('target',30,80),element('moving',5,30)];
 if(flow){p.kind='flow';p.bands=[{band_id:'first',type:'ReportHeader',height_mm:100,elements:[p.elements[1]]},{band_id:'second',type:'Detail',height_mm:100,elements:[p.elements[0]]}];p.elements=[];}
 d.getElementById('report-definition').textContent=JSON.stringify(definition);
 w.fetch=async url=>({ok:true,json:async()=>url==='/api/connections/'?{connections:[]}:{...fixture.report,definition,bindings:[]}});
 for(const file of ['magnetic.js','designer.js'])w.eval(fs.readFileSync(path.join(root,'reportbuilder/static/reportbuilder',file),'utf8'));
 await new Promise(resolve=>setTimeout(resolve,0));
 const pointer=(target,type,x,y,extra={})=>target.dispatchEvent(new w.MouseEvent(type,{bubbles:true,button:0,clientX:x,clientY:y,...extra}));
 const moving=()=>d.querySelector('[data-element-id="moving"]');
 const px=96/25.4;
 function drag(altKey=false){pointer(moving(),'pointerdown',0,0);pointer(d,'pointermove',24*px*.65,0,{altKey});}
 return {w,d,pointer,moving,px,drag};
}
test('drag snaps, draws guides, saves position and supports undo/redo',async t=>{
 const {d,pointer,moving,px,drag}=await designer(t);
 drag();
 assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,30);
 assert.equal(d.querySelectorAll('.alignment-guide').length,1);
 pointer(d,'pointerup',0,0);
 assert.equal(d.querySelectorAll('.alignment-guide').length,0);
 d.getElementById('undo').click();assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,5);
 d.getElementById('redo').click();assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,30);
});
test('Alt and toggle bypass snapping; cancellation restores geometry and clears guides',async t=>{
 const {w,d,pointer,moving,px,drag}=await designer(t);
 drag(true);assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,29);pointer(d,'pointerup',0,0);
 d.getElementById('undo').click();
 d.getElementById('magnetic-toggle').click();
 assert.equal(d.getElementById('magnetic-toggle').getAttribute('aria-pressed'),'false');
 drag();assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,29);pointer(d,'pointerup',0,0);
 d.getElementById('undo').click();d.getElementById('magnetic-toggle').click();
 drag();pointer(d,'pointercancel',0,0);
 assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,5);assert.equal(d.querySelectorAll('.alignment-guide').length,0);
 drag();d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,5);
});
test('repeating bands do not attract elements in another coordinate system',async t=>{
 const {d,pointer,moving,px,drag}=await designer(t,true);
 drag();assert.equal(Math.round(parseFloat(moving().style.left)/px*1000)/1000,29);
 assert.equal(d.querySelectorAll('.alignment-guide').length,0);
 pointer(d,'pointerup',0,0);
});
