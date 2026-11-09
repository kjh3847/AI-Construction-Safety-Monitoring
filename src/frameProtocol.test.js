import {test} from 'node:test';
import assert from 'node:assert/strict';
import {unpackFrame,textLabels} from './frameProtocol.js';

test('binary packet preserves camera/frame pairing and rejects another camera',()=>{
  const json=new TextEncoder().encode(JSON.stringify({camera_id:'CAM-02',frame_id:17}));
  const packet=new Uint8Array(4+json.length+3);
  new DataView(packet.buffer).setUint32(0,json.length);
  packet.set(json,4);packet.set([1,2,3],4+json.length);
  assert.equal(unpackFrame(packet.buffer,'CAM-02').meta.frame_id,17);
  assert.throws(()=>unpackFrame(packet.buffer,'CAM-01'),/불일치/);
});

test('text labels stay in bounds and separate overlapping people without boxes',()=>{
  const frame={annotation_mode:'text-metadata',person_safety:[0,1,2].map(i=>({
    bbox:[-5,8,100,200],local_track_id:i,violations:i ? [] : ['NO-Hardhat']}))};
  const labels=textLabels(frame,640,480,t=>t.length*8);
  assert.equal(new Set(labels.map(l=>l.y)).size,3);
  assert.ok(labels.every(l=>l.x>=0 && l.x+l.width<=640 && l.y>=20 && l.y<480));
  assert.equal(labels[0].danger,true);
  assert.match(labels[1].text,/미착용 증거 없음/);
  assert.deepEqual(textLabels({...frame,annotation_mode:undefined},640,480,()=>100),[]);
});
