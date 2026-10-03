'use strict';
const assert=require('node:assert/strict');
const test=require('node:test');
const {parse,validate,draw}=require('../../reportbuilder/static/reportbuilder/infographics.js');
test('chart inputs preserve zeros and negatives and reject malformed or excessive values',()=>{
 assert.deepEqual(parse('서울,120\n부산,0\n조정,-10','bar'),[{label:'서울',value:120},{label:'부산',value:0},{label:'조정',value:-10}]);
 for(const input of ['서울,','서울,NaN','서울,Infinity','서울,1e99','120',''])assert.throws(()=>parse(input,'bar'));
 assert.throws(()=>parse('A,-1','donut'));
 assert.throws(()=>parse('A,0','donut'));
 assert.throws(()=>validate(Array.from({length:25},()=>({label:'A',value:1})),'bar'));
});
test('every chart type renders from the same statistical values',()=>{
 const calls=[];
 const context=new Proxy({}, {get:(_target,key)=>()=>calls.push(key),set:()=>true});
 const canvas={getContext:()=>context};
 for(const type of ['bar','line','donut','kpi']){
  const points=parse('A,10\nB,20',type);
  assert.deepEqual(draw(canvas,points,{type,title:'통계',unit:'건',color:'#4f46e5'}),points);
 }
 assert.equal(canvas.width,1280);assert.equal(canvas.height,720);
 assert(calls.includes('arc'));assert(calls.includes('fillText'));assert(calls.includes('lineTo'));
});
