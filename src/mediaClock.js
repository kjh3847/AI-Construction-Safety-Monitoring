export class MetadataBuffer {
  constructor(cameraId){this.cameraId=cameraId;this.generation=null;this.frames=new Map();}
  add(meta,now=performance.now()){
    if(meta.camera_id!==this.cameraId || !Number.isInteger(meta.media_clock?.rtp_timestamp))return false;
    if(meta.source_generation!==this.generation){this.frames.clear();this.generation=meta.source_generation;}
    this.frames.set(meta.media_clock.rtp_timestamp>>>0,{meta,arrival:now});
    while(this.frames.size>60)this.frames.delete(this.frames.keys().next().value);
    for(const [key,value] of this.frames)if(now-value.arrival>3000)this.frames.delete(key);
    return true;
  }
  exact(timestamp,now=performance.now()){
    if(!Number.isInteger(timestamp))return null;
    const entry=this.frames.get(timestamp>>>0);
    return entry && now-entry.arrival<=3000 ? entry.meta : null;
  }
  recent(timestamp,now=performance.now()){
    if(!Number.isInteger(timestamp))return null;
    let closest=null, distance=27001;
    for(const [key,entry] of this.frames){
      const lag=(timestamp-key)>>>0;
      if(lag<distance && now-entry.arrival<=700){
        distance=lag;
        closest=entry.meta;
      }
    }
    return closest;
  }
}
