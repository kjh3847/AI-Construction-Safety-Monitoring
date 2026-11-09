import {test} from 'node:test';
import assert from 'node:assert/strict';
import {MetadataBuffer} from './mediaClock.js';

const meta=(timestamp,generation='first',camera='CAM-01')=>({camera_id:camera,source_generation:generation,media_clock:{rtp_timestamp:timestamp}});
test('overlay requires exact RTP timestamp and the same camera',()=>{
  const buffer=new MetadataBuffer('CAM-01');buffer.add(meta(123),100);
  assert.equal(buffer.exact(123,200).camera_id,'CAM-01');assert.equal(buffer.exact(124,200),null);
  assert.equal(buffer.add(meta(125,'first','CAM-02'),200),false);
});
test('publisher restart and expiration discard stale overlays',()=>{
  const buffer=new MetadataBuffer('CAM-01');buffer.add(meta(123),100);buffer.add(meta(456,'second'),200);
  assert.equal(buffer.exact(123,200),null);assert.equal(buffer.exact(456,4000),null);
});
test('unsigned RTP rollover is matched exactly and buffer stays bounded',()=>{
  const buffer=new MetadataBuffer('CAM-01');buffer.add(meta(4294967295),0);
  assert.ok(buffer.exact(-1,1));
  for(let i=0;i<100;i++)buffer.add(meta(i),100);
  assert.ok(buffer.frames.size<=60);
});
