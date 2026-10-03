'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {snap} = require('../../reportbuilder/static/reportbuilder/magnetic.js');
const bounds = {threshold:2, maxWidth:180, maxHeight:260};
const box = (x,y,w=20,h=10) => ({x_mm:x,y_mm:y,width_mm:w,height_mm:h});

test('aligns edges and centres independently to the nearest candidate', () => {
 const result = snap(box(31,49), [box(30,80),box(100,50)], bounds);
 assert.equal(result.geometry.x_mm,30);
 assert.equal(result.geometry.y_mm,50);
 assert.equal(result.guides.length,2);
 const centred = snap(box(34,70,10),[box(30,100,20)],bounds);
 assert.equal(centred.geometry.x_mm,35);
});
test('does not attract distant elements or snap outside the surface', () => {
 assert.deepEqual(snap(box(30,40),[box(90,100)],bounds).geometry,box(30,40));
 const result = snap(box(0,20,20),[box(0,80,19)],bounds);
 assert(result.geometry.x_mm>=0);
 const edge = snap(box(160,20,20),[box(179,100,2)],bounds);
 assert(edge.geometry.x_mm+edge.geometry.width_mm<=180);
});
test('resize aligns trailing edges without moving the origin', () => {
 const result = snap(box(10,20,29,19),[box(40,40)],{...bounds,resizing:true});
 assert.deepEqual(result.geometry,box(10,20,30,20));
});
test('screen tolerance stays six pixels at all supported zoom levels', () => {
 for(const zoom of [.55,.65,.8,1,1.25]){
  const threshold=6/(96/25.4*zoom);
  assert(Math.abs(snap(box(30+threshold-.01,70),[box(30,100)],{...bounds,threshold}).geometry.x_mm-30)<1e-9);
  assert.equal(snap(box(30+threshold+.01,70),[box(30,100)],{...bounds,threshold}).guides.length,0);
 }
});
