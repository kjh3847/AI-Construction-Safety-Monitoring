import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Play, Pause, SkipBack, SkipForward, Radio, Maximize, PanelRightClose, PanelRightOpen } from 'lucide-react';

const BASE = 'http://127.0.0.1:8002';
const timeLabel = (timestamp) => timestamp == null ? '—' : new Date(timestamp * 1000).toLocaleTimeString('ko-KR');
export const stateLabel = {idle:'감지 대기', starting:'연결 중', running:'감지 중', stopping:'감지 종료 중', stopped:'감지 중단', finished:'테스트 영상 종료', disconnected:'카메라 연결 끊김', error:'감지 오류'};

export default function MonitorPlayer({ cameraId, status, connection, enabled, onFrame, jump, expanded, onExpand, onFullscreen, isFullscreen }) {
  const [mode, setMode] = useState('live');
  const [paused, setPaused] = useState(false);
  const [frame, setFrame] = useState(null);
  const [position, setPosition] = useState(null);
  const [seekVersion, setSeekVersion] = useState(0);
  const [error, setError] = useState('');
  const canvas = useRef(null);
  const statusRef = useRef(status);
  const target = useRef(null);
  const displayed = useRef(null);
  const callback = useRef(onFrame);
  statusRef.current = status;
  callback.current = onFrame;
  const bounds = status?.buffer;
  const available = bounds?.start != null;

  useLayoutEffect(() => {
    if (!frame || !canvas.current) return;
    const image = frame.decoded;
    canvas.current.width = image.naturalWidth;
    canvas.current.height = image.naturalHeight;
    canvas.current.getContext('2d').drawImage(image, 0, 0);
  }, [frame]);

  useEffect(() => {
    if (!jump) return;
    target.current = jump.timestamp;
    setPosition(jump.timestamp);
    setMode('past');
    setPaused(true);
    setSeekVersion((n) => n + 1);
  }, [jump]);

  useEffect(() => {
    callback.current(frame ? { ...frame, paused, mode } : null);
  }, [mode, paused]);

  useEffect(() => {
    if (!enabled) {
      setFrame(null);
      displayed.current = null;
      callback.current(null);
      return;
    }
    let active = true;
    let timer;
    let previousClock = performance.now();
    const controller = new AbortController();
    async function tick() {
      const buffer = statusRef.current?.buffer;
      if (!buffer || buffer.start == null) {
        setError('아직 저장된 영상이 없습니다. 감지를 시작하세요.');
        if (active) timer = setTimeout(tick, 500);
        return;
      }
      // A paused picture remains frozen even when its disk recording expires.
      // Only explicit seek/play/live actions start a new request cycle.
      const now = performance.now();
      let at = null;
      if (mode === 'past' || paused) {
        at = target.current ?? displayed.current?.timestamp ?? buffer.end;
        if (!paused) at += (now - previousClock) / 1000;
        if (at < buffer.start) {
          setError('이 재생 위치의 녹화가 만료되었습니다. 타임라인을 선택하거나 실시간으로 돌아가세요.');
          return;
        }
        at = Math.min(at, buffer.end);
        target.current = at;
      }
      previousClock = now;
      try {
        const response = await fetch(`${BASE}/api/recordings/frame?camera_id=${cameraId}${at == null ? '' : `&at=${at}`}`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]), cache:'no-store',
        });
        if (!response.ok) throw new Error(response.status === 410 ? '재생 가능한 영상 없음 · 보관 범위를 다시 선택하세요.' : '영상 조회 실패');
        const data = await response.json();
        const decoded = new Image();
        decoded.src = data.image;
        await decoded.decode();
        if (!active) return;
        displayed.current = data;
        setFrame({...data, decoded});
        setPosition(data.timestamp);
        setError('');
        callback.current({...data, mode, paused});
      } catch (exc) {
        if (!active) return;
        setError(exc.message === 'Failed to fetch' ? '영상 서버 연결 실패' : exc.message);
        callback.current(null);
      }
      if (active && !paused) timer = setTimeout(tick, 200);
    }
    tick();
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [enabled, mode, paused, seekVersion, cameraId]);

  function seek(value) {
    if (!available) return;
    const at = Math.max(bounds.start, Math.min(Number(value), bounds.end));
    target.current = at;
    setPosition(at);
    setMode('past');
    setSeekVersion((n) => n + 1);
  }
  function togglePause() {
    if (paused) {
      setMode('past');
      target.current = displayed.current?.timestamp;
    } else {
      target.current = displayed.current?.timestamp;
      setMode('past');
    }
    setPaused(!paused);
  }
  function goLive() {
    setMode('live'); setPaused(false); target.current = null;
    setSeekVersion((n) => n + 1);
  }
  const fresh = connection === 'ready' && status?.state === 'running' && frame?.recording_id === status?.recording_id
    && Date.now()/1000 - frame?.timestamp < 10;
  const label = paused ? '일시정지 · 과거 화면' : mode === 'past' ? '과거 재생' : fresh ? (status?.source_kind === 'test' ? '테스트 영상 · 현재' : 'LIVE · 실시간') : stateLabel[status?.state] ?? '연결 중';
  return <>
    <div className="dvr-picture">
      <canvas ref={canvas} role="img" aria-label="재생 시점의 YOLO 감지 영상" hidden={!frame}/>
      {!frame && <div className="empty-feed"><Radio size={36}/><h3>{enabled ? '영상 버퍼 준비' : '연결된 카메라가 없습니다'}</h3></div>}
      <div className="video-labels"><span>{frame?.camera_name ?? status?.camera_name ?? 'CAM-01'}</span><span className={fresh && mode === 'live' ? 'signal-good' : 'signal-caution'}>{label}</span><span>{mode === 'past' || paused ? '재생 시점' : '현재'} 감지 {connection === 'ready' && frame && (fresh || mode === 'past' || paused) ? `${frame.person_count}명` : '—'}</span><span>{timeLabel(frame?.timestamp)}</span></div>
      {(connection !== 'ready' || error) && <div className="video-message" role="status">{connection === 'loading' ? '서버 연결 중' : connection === 'error' ? '서버 연결 실패 · 마지막 화면' : error}</div>}
      {frame?.source_kind === 'test' && <span className="source-label">테스트 영상 · {frame.source_name} · 원본 {frame.video_seconds.toFixed(1)}초</span>}
      {connection === 'ready' && frame && (fresh || mode === 'past' || paused) && <span className="person-count-label">미착용 추정 {frame.noncompliant_person_count == null ? '—' : `${frame.noncompliant_person_count}명`}{frame.unassigned_negative_count > 0 ? ` · 연결 불가 ${frame.unassigned_negative_count}건` : ''}</span>}
      {connection === 'ready' && frame && (fresh || mode === 'past' || paused) && <span className={`risk-label ${frame.negative_detection_count > 0 ? 'signal-danger' : 'signal-good'}`}>{frame.negative_detection_count > 0 ? '⚠ 보호구 미착용 의심 감지' : '✓ 미착용 클래스 감지 없음'}</span>}
    </div>
    <div className="playback-toolbar">
      <button onClick={togglePause} disabled={!frame || !enabled} title="화면만 일시정지합니다. 서버 감지와 녹화는 계속됩니다.">{paused ? <Play size={16}/> : <Pause size={16}/>} {paused ? '재생' : '화면 일시정지'}</button>
      <button onClick={() => seek((position ?? bounds.end) - 10)} disabled={!available || !enabled}><SkipBack size={16}/>10초 전</button>
      <button onClick={() => seek((position ?? bounds.end) + 10)} disabled={!available || !enabled}><SkipForward size={16}/>10초 후</button>
      <button onClick={goLive} disabled={!available || !enabled} className="live-button"><Radio size={16}/>실시간으로 돌아가기</button>
      <button onClick={onExpand}>{expanded ? <PanelRightOpen size={16}/> : <PanelRightClose size={16}/>} {expanded ? '이력 펼치기' : '확대 보기'}</button>
      <button onClick={onFullscreen}><Maximize size={16}/>{isFullscreen ? '전체화면 종료' : '전체화면'}</button>
    </div>
    <div className="timeline">
      <input aria-label="저장된 영상 시간 탐색" type="range" min={bounds?.start ?? 0} max={bounds?.end ?? 0} step="0.05"
        value={available ? Math.max(bounds.start, Math.min(position ?? bounds.end, bounds.end)) : 0}
        disabled={!available || !enabled} onChange={(event) => seek(event.target.value)}/>
      <div><span>{timeLabel(bounds?.start)}</span><span>저장 구간 {available ? Math.floor(bounds.end - bounds.start) : 0}초 / 보관 설정 {bounds?.retention_seconds ?? 300}초</span><span>{timeLabel(bounds?.end)}</span></div>
      {bounds?.capacity_limited && <p className="signal-caution">용량 한도로 실제 보관 구간이 설정 시간보다 짧을 수 있습니다.</p>}
    </div>
  </>;
}
