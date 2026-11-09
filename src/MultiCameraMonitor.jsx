import React, {useEffect, useRef, useState} from 'react';
import MonitorPlayer, {stateLabel} from './MonitorPlayer';
import {cameras} from './data';
import {accountRequest} from './api';

function CameraTile({camera, status, connection, jump, onFrame}) {
  const shell = useRef(null);
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState('');
  const [expanded,setExpanded] = useState(false);
  const [fullscreen,setFullscreen] = useState(false);
  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === shell.current);
    document.addEventListener('fullscreenchange',sync);
    return () => document.removeEventListener('fullscreenchange',sync);
  },[]);
  useEffect(() => { if (jump) shell.current?.scrollIntoView({behavior:'smooth',block:'center'}); },[jump]);
  async function control(action) {
    setBusy(true);
    try { await accountRequest(`/api/monitor/${action}?camera_id=${camera.id}`,{method:'POST'}); setMessage(''); }
    catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  }
  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === shell.current) await document.exitFullscreen();
      else await shell.current?.requestFullscreen();
    } catch { setMessage('전체화면을 열 수 없습니다.'); }
  }
  return <section className={`panel camera-tile ${expanded ? 'tile-expanded' : ''}`} data-camera-id={camera.id}>
    <div className="section-title"><h2>{camera.id}{status?.camera_name && status.camera_name !== camera.id ? ` · ${status.camera_name}` : ''}</h2>
      <span className={status?.state === 'running' ? 'signal-good' : 'signal-caution'}>{connection === 'ready' ? stateLabel[status?.state] : '서버 연결 중'}</span></div>
    <div className="player-shell" ref={shell}>
      <MonitorPlayer cameraId={camera.id} status={status} connection={connection} enabled={Boolean(status?.configured)}
        onFrame={frame => onFrame(camera.id,frame)} jump={jump} expanded={expanded} onExpand={() => setExpanded(v=>!v)}
        onFullscreen={toggleFullscreen} isFullscreen={fullscreen}/>
    </div>
    <div className="feed-footer">
      <button className="primary" disabled={busy || !status?.configured || ['running','starting','reconnecting','stopping'].includes(status?.state)} onClick={()=>control('start')}>감지·녹화 시작</button>
      <button className="danger-button" disabled={busy || !['running','starting','reconnecting','disconnected'].includes(status?.state)} onClick={()=>control('stop')}>중단</button>
    </div>
    <p className="small-note">입력 {status?.metrics?.capture_fps ?? '—'} FPS · 분석 {status?.metrics?.analysis_fps ?? '—'} FPS · 처리 지연 {status?.metrics?.frame_age_ms ?? '—'} ms</p>
    <p className="small-note">현재 감지 {status?.current_counts?.person_count ?? '—'}명 · 미착용 추정 {status?.current_counts?.noncompliant_person_count ?? '—'}명</p>
    {status?.duplicate_source && <p className="connection-note">다른 카메라와 입력 주소가 중복됩니다.</p>}
    {(message || status?.error || status?.storage_error) && <p className="connection-note" role="status">{message || status?.error || status?.storage_error}</p>}
  </section>;
}

export default function MultiCameraMonitor({jump, onTotals}) {
  const [statuses,setStatuses] = useState({});
  const [connection,setConnection] = useState('loading');
  const [message,setMessage] = useState('');
  const [busy,setBusy] = useState(false);
  const frames = useRef({});
  const statusesRef = useRef(statuses);
  statusesRef.current = statuses;
  const totalsCallback = useRef(onTotals);
  totalsCallback.current = onTotals;
  const [tracklets,setTracklets] = useState([]);
  const [reid,setReid] = useState('disabled');
  const [service,setService] = useState(null);
  useEffect(() => {
    let active=true, timer;
    async function refresh() {
      const results = await Promise.allSettled([accountRequest('/api/cameras'),accountRequest('/api/people?limit=20')]);
      if (!active) return;
      if (results[0].status === 'fulfilled') {
        setStatuses(Object.fromEntries(results[0].value.cameras.map(s=>[s.camera_id,s])));
        setReid(results[0].value.reid_state); setConnection('ready');
        setService(results[0].value.service_metrics);
      } else setConnection('error');
      if (results[1].status === 'fulfilled') setTracklets(results[1].value.tracklets);
      publishTotals();
      timer=setTimeout(refresh,2000);
    }
    refresh();
    return () => {active=false;clearTimeout(timer);};
  },[]);
  function publishTotals() {
    const live = Object.values(frames.current).filter(f => f && !f.paused && f.mode === 'live'
      && statusesRef.current[f.camera_id]?.state === 'running' && Date.now()/1000-f.timestamp < 10);
    totalsCallback.current?.({people:live.reduce((n,f)=>n+f.person_count,0),
      violations:live.reduce((n,f)=>n+(f.noncompliant_person_count ?? 0),0), active:live.length});
  }
  function receiveFrame(id,frame) {frames.current[id]=frame;publishTotals();}
  async function controlAll(action) {
    setBusy(true);
    try {await accountRequest(`/api/monitor/${action}?camera_id=all`,{method:'POST'});setMessage('');}
    catch(e) {setMessage(e.message);} finally {setBusy(false);}
  }
  async function correct(event,tracklet) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await accountRequest('/api/people/correction',{method:'PATCH',body:JSON.stringify({
        tracklet_id:tracklet.id,global_person_id:form.get('target') || null,reason:form.get('reason')})});
      setMessage('추적 연결을 수정했습니다. 원본 프레임에는 당시 분석 결과가 보존됩니다.');
    } catch(e) {setMessage(e.message);}
  }
  return <>
    <div className="multi-controls"><button className="primary" disabled={busy} onClick={()=>controlAll('start')}>전체 감지·녹화 시작</button>
      <button className="danger-button" disabled={busy} onClick={()=>controlAll('stop')}>전체 중단</button>
      <span>ReID {reid === 'ready' ? '모델 활성' : reid === 'disabled' ? '모델 미설정 · 카메라 간 자동 연결 비활성' : reid}</span></div>
    {service && <p className="small-note">서버 CPU {service.cpu_percent.toFixed(1)}% · 메모리 {(service.rss_bytes/1024**2).toFixed(0)} MiB · 디스크 여유 {(service.disk_free_bytes/1024**3).toFixed(1)} GiB</p>}
    {message && <p role="status">{message}</p>}
    <div className="multi-camera-grid">{cameras.map(camera => <CameraTile key={camera.id} camera={camera}
      status={statuses[camera.id]} connection={connection} onFrame={receiveFrame}
      jump={jump?.cameraId === camera.id ? jump : null}/>)}</div>
    <section className="panel tracking-panel"><h2>익명 작업자 이동 기록</h2><p>Global ID는 추정 연결입니다. 미확정 기록은 동일인으로 확인되지 않았습니다.</p>
      {tracklets.length === 0 ? <p>아직 추적 기록이 없습니다.</p> : <div className="tracking-list">{tracklets.map(t=><details key={t.id}>
        <summary>{t.global_person_id} · {t.camera_id} / Local {t.local_track_id} · {t.match_state} · 유사도 {t.similarity?.toFixed(3) ?? '—'}</summary>
        <p>{new Date(t.first_seen*1000).toLocaleString('ko-KR')} ~ {new Date(t.last_seen*1000).toLocaleString('ko-KR')} · 근거: {t.reason}</p>
        <form onSubmit={e=>correct(e,t)}><label>연결할 Global ID (비우면 분리)<input name="target" pattern="P[A-F0-9]{16}"/></label>
          <label>수정 사유<input name="reason" required minLength={3} maxLength={500}/></label><button type="submit">연결 수정</button></form>
      </details>)}</div>}
    </section>
  </>;
}
