export function unpackFrame(buffer, cameraId) {
  const view = new DataView(buffer);
  const length = view.getUint32(0);
  if (length > 1024 * 1024 || length + 4 >= buffer.byteLength) throw new Error('잘못된 영상 패킷');
  const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, length)));
  if (meta.camera_id !== cameraId) throw new Error('카메라 영상 식별자 불일치');
  return {meta, image: new Blob([buffer.slice(length + 4)], {type:'image/jpeg'})};
}

const names = {'NO-Hardhat':'안전모 미착용 의심', 'NO-Safety Vest':'안전조끼 미착용 의심'};
export function textLabels(meta, width, height, measure) {
  if (meta.annotation_mode !== 'text-metadata') return [];
  const placed = [];
  for (const person of meta.person_safety ?? []) {
    if (!person.bbox) continue;
    const identity = person.global_person_id ?? `L${person.local_track_id}`;
    const suffix = person.match_state === 'estimated' ? ' (추정)' : person.match_state === 'manual' ? ' (수정)' : ' (미확정)';
    const status = person.violations.length ? person.violations.map(v => names[v] ?? v).join(' · ') : '미착용 증거 없음';
    const text = `${identity}${suffix} · ${status}`;
    const labelWidth = Math.min(width, measure(text));
    const x = Math.max(0, Math.min(width-labelWidth, person.bbox[0]));
    let y = Math.max(20, Math.min(height-4, person.bbox[1]-8));
    for (let attempt=0; attempt < Math.ceil(height/22); attempt++) {
      if (!placed.some(p => Math.abs(p.y-y) < 22 && x < p.x+p.width && x+labelWidth > p.x)) break;
      y = y+22 < height ? y+22 : 20;
    }
    placed.push({text,x,y,width:labelWidth,danger:person.violations.length > 0});
  }
  return placed;
}
