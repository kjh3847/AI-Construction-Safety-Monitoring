import React, {useEffect, useRef, useState} from 'react';
import MonitorPlayer, {stateLabel} from './MonitorPlayer';
import {accountRequest} from './api';

function CameraTile({camera, status, connection, jump, onFrame, onStatus, exhibition, canOperate}) {
  const shell = useRef(null);
  const videoInput = useRef(null);
  const [busy,setBusy] = useState(false);
  const [progress,setProgress] = useState(null);
  const [message,setMessage] = useState('');
  const [expanded,setExpanded] = useState(false);
  const [fullscreen,setFullscreen] = useState(false);
  const testCamera = camera.input === 'video';
  const canRegister = exhibition && canOperate && !testCamera && status?.input_adapter === 'direct';

  async function register(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const url = new FormData(form).get('url');
    setBusy(true);
    try {
      onStatus(await accountRequest('/api/cameras/' + camera.id + '/source', {
        method: 'POST', body: JSON.stringify({url}),
      }));
      form.reset();
      setMessage('카메라 주소를 저장했습니다.');
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }
  const recording = ['running','starting','reconnecting','stopping'].includes(status?.state);
  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === shell.current);
    document.addEventListener('fullscreenchange',sync);
    return () => document.removeEventListener('fullscreenchange',sync);
  },[]);
  useEffect(() => { if (jump) shell.current?.scrollIntoView({behavior:'smooth',block:'center'}); },[jump]);
  async function control(action) {
    setBusy(true);
    try { onStatus(await accountRequest(`/api/monitor/${action}?camera_id=${camera.id}`,{method:'POST'})); setMessage(''); }
    catch (e) { setMessage(e.message); }
    finally { setBusy(false); }
  }
  async function upload(file) {
    if (!file) return;
    if (!file.size || file.size > 300 * 1024 * 1024) {
      setMessage('300 MiB 이하의 영상 파일을 선택하세요.');
      return;
    }
    setProgress(0);
    setMessage('');
    try {
      const uploadId = crypto.randomUUID();
      const chunkSize = 512 * 1024;
      for (let offset = 0; offset < file.size; offset += chunkSize) {
        const query = new URLSearchParams({upload_id:uploadId, offset, total:file.size});
        const result = await accountRequest(`/api/cameras/${camera.id}/upload?${query}`, {
          method:'POST', headers:{'Content-Type':'application/octet-stream'},
          body:file.slice(offset, offset + chunkSize),
        });
        setProgress(Math.floor(result.received / file.size * 100));
      }
      onStatus(await accountRequest('/api/status?camera_id=' + camera.id));
      setMessage(exhibition ? '업로드 완료 · 반복 재생을 시작합니다.' : '업로드 완료 · 감지·녹화 시작을 누르세요.');
    } catch (e) { setMessage(e.message); }
    finally { setProgress(null); }
  }
  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === shell.current) await document.exitFullscreen();
      else await shell.current?.requestFullscreen();
    } catch { setMessage('전체화면을 열 수 없습니다.'); }
  }
  return <section className={`panel camera-tile ${expanded ? 'tile-expanded' : ''}`} data-camera-id={camera.id}>
    <div className="section-title"><h2>{camera.id}{testCamera ? (exhibition ? ' · ' + camera.name : ' · 테스트 영상') : status?.camera_name && status.camera_name !== camera.id ? ` · ${status.camera_name}` : ''}</h2>
      <span className={status?.state === 'running' ? 'signal-good' : 'signal-caution'}>{connection === 'ready' ? stateLabel[status?.state] : '서버 연결 중'}</span></div>
    <div className="player-shell" ref={shell}>
      <MonitorPlayer cameraId={camera.id} status={status} connection={connection} enabled={Boolean(status?.configured)}
        onFrame={frame => onFrame(camera.id,frame)} jump={jump} expanded={expanded} onExpand={() => setExpanded(v=>!v)}
        onFullscreen={toggleFullscreen} isFullscreen={fullscreen}/>
    </div>
    {canOperate && <div className="feed-footer">
      <button className="primary" disabled={busy || progress !== null || !status?.configured || recording} onClick={()=>control('start')}>감지·녹화 시작</button>
      <button className="danger-button" disabled={busy || !['running','starting','reconnecting','disconnected'].includes(status?.state)} onClick={()=>control('stop')}>중단</button>
      {testCamera && <>
        <input ref={videoInput} type="file" accept="video/*,.mkv,.avi" hidden onChange={event=>{
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = '';
          upload(file);
        }}/>
        <button type="button" disabled={busy || recording || progress !== null} onClick={()=>videoInput.current?.click()}>
          {progress === null ? '영상 업로드' : `업로드 ${progress}%`}
        </button>
      </>}
    </div>}
    {canRegister && <form className="camera-registration" onSubmit={register}>
      <label>스트림 주소<input name="url" type="url" placeholder="rtsp:// 또는 https://" required maxLength={2048}/></label>
      <button disabled={busy || recording}>등록 및 연결</button>
    </form>}
    <p className="small-note">입력 {status?.metrics?.capture_fps ?? '—'} FPS · 분석 {status?.metrics?.analysis_fps ?? '—'} FPS · 처리 지연 {status?.metrics?.frame_age_ms ?? '—'} ms</p>
    {status?.relay && <p className="small-note">영상 {status.relay.online ? '연결됨' : '연결 안 됨'} · 최근 수신 {status.relay.last_received ? new Date(status.relay.last_received*1000).toLocaleTimeString('ko-KR') : '대기'} · AI {stateLabel[status?.state] ?? status?.state}</p>}
    <p className="small-note">현재 감지 {status?.current_counts?.person_count ?? '—'}명 · 미착용 추정 {status?.current_counts?.noncompliant_person_count ?? '—'}명</p>
    {status?.duplicate_source && <p className="connection-note">다른 카메라와 입력 주소가 중복됩니다.</p>}
    {(message || status?.error || status?.storage_error) && <p className="connection-note" role="status">{message || status?.error || status?.storage_error}</p>}
  </section>;
}

export default function MultiCameraMonitor({jump, onTotals, cameras, exhibition, canOperate}) {
  const cameraStrip = useRef(null);
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
      const results = await Promise.allSettled([accountRequest('/api/cameras'), exhibition ? Promise.resolve({tracklets: []}) : accountRequest('/api/people?limit=20')]);
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
  },[exhibition]);
  function showCamera(id, behavior = 'smooth') {
    const strip = cameraStrip.current;
    const tile = strip?.querySelector('[data-camera-id="' + id + '"]');
    if (tile) strip.scrollBy({left: tile.getBoundingClientRect().left - strip.getBoundingClientRect().left, behavior});
  }
  useEffect(() => {
    if (exhibition && !jump) showCamera('CAM-04', 'instant');
  }, [exhibition, jump]);
  function publishTotals() {
    const live = Object.values(frames.current).filter(f => f && !f.paused && f.mode === 'live'
      && statusesRef.current[f.camera_id]?.state === 'running' && Date.now()/1000-f.timestamp < 10);
    totalsCallback.current?.({people:live.reduce((n,f)=>n+f.person_count,0),
      violations:live.reduce((n,f)=>n+(f.noncompliant_person_count ?? 0),0), active:live.length});
  }
  function receiveFrame(id,frame) {frames.current[id]=frame;publishTotals();}
  async function controlAll(action) {
    setBusy(true);
    try {
      const result = await accountRequest(`/api/monitor/${action}?camera_id=all`,{method:'POST'});
      setStatuses(Object.fromEntries(result.cameras.map(status=>[status.camera_id,status])));
      setMessage('');
    }
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
    <div className="multi-controls">{canOperate && <><button className="primary" disabled={busy} onClick={()=>controlAll('start')}>전체 감지·녹화 시작</button>
      <button className="danger-button" disabled={busy} onClick={()=>controlAll('stop')}>전체 중단</button></>}
      {!exhibition && <span>ReID {reid === 'ready' ? '모델 활성' : reid === 'disabled' ? '모델 미설정 · 카메라 간 자동 연결 비활성' : reid}</span>}
      <div className="camera-scroll-controls">
        {exhibition ? cameras.map(camera => <button key={camera.id} type="button" onClick={() => showCamera(camera.id)} aria-label={camera.id + ' ' + camera.name}>{camera.id}</button>) : <>
        <button type="button" onClick={()=>cameraStrip.current?.scrollBy({left:-cameraStrip.current.clientWidth,behavior:'smooth'})}>← 이전 카메라</button>
        <button type="button" onClick={()=>cameraStrip.current?.scrollBy({left:cameraStrip.current.clientWidth,behavior:'smooth'})}>다음 카메라 →</button></>}
      </div></div>
    {service && canOperate && <p className="small-note">서버 CPU {service.cpu_percent.toFixed(1)}% · 메모리 {(service.rss_bytes/1024**2).toFixed(0)} MiB · 디스크 여유 {(service.disk_free_bytes/1024**3).toFixed(1)} GiB</p>}
    {message && <p role="status">{message}</p>}
    <div className="multi-camera-grid" data-exhibition={exhibition || undefined} ref={cameraStrip} aria-label="카메라 가로 목록" tabIndex={0}>{cameras.map(camera => <CameraTile key={camera.id} camera={camera}
      exhibition={exhibition} canOperate={canOperate} status={statuses[camera.id]} connection={connection} onFrame={receiveFrame}
      onStatus={status=>setStatuses(previous=>({...previous,[status.camera_id]:status}))}
      jump={jump?.cameraId === camera.id ? jump : null}/>)}</div>
    {!exhibition && <section className="panel tracking-panel"><h2>익명 작업자 이동 기록</h2><p>Global ID는 추정 연결입니다. 미확정 기록은 동일인으로 확인되지 않았습니다.</p>
      {tracklets.length === 0 ? <p>아직 추적 기록이 없습니다.</p> : <div className="tracking-list">{tracklets.map(t=><details key={t.id}>
        <summary>{t.global_person_id} · {t.camera_id} / Local {t.local_track_id} · {t.match_state} · 유사도 {t.similarity?.toFixed(3) ?? '—'}</summary>
        <p>{new Date(t.first_seen*1000).toLocaleString('ko-KR')} ~ {new Date(t.last_seen*1000).toLocaleString('ko-KR')} · 근거: {t.reason}</p>
        <form onSubmit={e=>correct(e,t)}><label>연결할 Global ID (비우면 분리)<input name="target" pattern="P[A-F0-9]{16}"/></label>
          <label>수정 사유<input name="reason" required minLength={3} maxLength={500}/></label><button type="submit">연결 수정</button></form>
      </details>)}</div>}
    </section>}
  </>;
}
