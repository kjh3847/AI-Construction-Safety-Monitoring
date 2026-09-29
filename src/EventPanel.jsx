import React, { useEffect, useRef, useState } from 'react';
import { Bell, Check, Download, ImageOff, X, Play } from 'lucide-react';
import { cameras } from './data';
const BASE = 'http://127.0.0.1:8002';
const cameraLabel = (event) => {
  const source = cameras.find((item) => item.id === (event.camera_id ?? event.camera_name));
  return source ? `${source.name} (${event.camera_name})` : event.camera_name;
};
export const eventName = (name) => ({'NO-Hardhat':'안전모 미착용 의심', 'NO-Safety Vest':'안전조끼 미착용 의심'}[name] ?? (name.startsWith('TEST_') ? `${name} · 기존 테스트` : name));

function EventFacts({event, detailed = false}) {
  const timestamp = event.detected_at ?? event.created_at;
  const date = new Date(timestamp);
  const clock = date.toLocaleTimeString('en-GB', {timeZone:'Asia/Seoul', hourCycle:'h23', hour:'2-digit', minute:'2-digit', second:'2-digit'}).split(':');
  const videoSeconds = event.video_seconds;
  const videoTime = videoSeconds == null ? null : [Math.floor(videoSeconds/3600), Math.floor(videoSeconds/60)%60, Math.floor(videoSeconds)%60].map((n) => String(n).padStart(2,'0')).join(':');
  return <div className="event-facts">
    {event.event_reason === 'sustained' && <strong className="sustained-warning">⚠ {Math.floor((event.sustained_seconds ?? 600)/60)}분 이상 미착용 지속 · 현장 확인 필요</strong>}
    <time dateTime={timestamp}>
      <span>{date.toLocaleDateString('ko-KR',{timeZone:'Asia/Seoul'})} · 한국 시간</span>
      <strong>{event.detected_at ? '감지' : '기록'} {clock[0]}시 {clock[1]}분 {clock[2]}초</strong>
    </time>
    {videoTime && <span>영상 위치 {videoTime}</span>}
    <strong className="event-people">해당 미착용 추정 {event.event_person_count == null ? '기록 없음' : `${event.event_person_count}명`}</strong>
    {event.person_track_id && <span>추적 인물 #{event.person_track_id} · {event.event_reason === 'sustained' ? '지속 미착용 재알림' : '최초 기록'}</span>}
    <span>당시 감지 인원 {event.person_count == null ? '기록 없음' : `${event.person_count}명`}</span>
    {detailed && <span>당시 전체 보호구 미착용 추정 {event.noncompliant_person_count == null ? '기록 없음' : `${event.noncompliant_person_count}명`}</span>}
    {event.unassigned_negative_count > 0 && <span className="signal-caution">당시 사람 연결 불가 {event.unassigned_negative_count}건 · 인원 제외</span>}
  </div>;
}
function Snapshot({event}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [event.id, event.snapshot_url]);
  return event.snapshot_url && !failed ? <img src={`${BASE}${event.snapshot_url}`} alt="실제 감지 스냅샷" onError={() => setFailed(true)}/> : <div className="snapshot-empty"><ImageOff size={22}/><span>스냅샷 없음</span></div>;
}
export default function EventPanel({events, connection, summary, filter, setFilter, equipment, setEquipment, day, setDay, review, exportCsv, onJump, loadMore, canLoadMore}) {
  const sustainedWarnings = events.filter((event) => event.event_reason === 'sustained' && event.review_status !== 'reviewed');
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState('');
  const [newIds, setNewIds] = useState(new Set());
  const seen = useRef(new Set());
  const initialized = useRef(false);
  const filterKey = `${filter}/${equipment}/${day}`;
  const previousFilter = useRef(filterKey);
  const closeRef = useRef(null);
  useEffect(() => {
    if (connection !== 'ready') return;
    const isNewFilter = previousFilter.current !== filterKey;
    const added = events.filter((event) => !seen.current.has(event.id));
    if (initialized.current && !isNewFilter && added.length) setNewIds(new Set(added.map((event) => event.id)));
    if (isNewFilter) setNewIds(new Set());
    events.forEach((event) => seen.current.add(event.id));
    initialized.current = true;
    previousFilter.current = filterKey;
  }, [events, connection, filterKey]);
  useEffect(() => {
    if (selected == null) return;
    let active = true;
    let timer;
    setDetail(null); setDetailError('');
    closeRef.current?.focus();
    const refresh = async () => {
      try {
        const response = await fetch(`${BASE}/api/events/${selected}`, {signal:AbortSignal.timeout(5000)});
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (active) { setDetail(data); setDetailError(''); }
      } catch { if (active) setDetailError('상세 정보 조회 실패 · 서버 연결을 확인하세요.'); }
      if (active) timer = setTimeout(refresh, 2000);
    };
    refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [selected]);
  useEffect(() => {
    if (selected == null) return;
    const handleKey = (event) => {
      if (event.key === 'Escape') setSelected(null);
      if (event.key === 'Tab') {
        const buttons = [...closeRef.current.closest('[role="dialog"]').querySelectorAll('button:not(:disabled)')];
        if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [selected]);
  return <section className="panel event-panel">
    <div className="section-title"><div><h2><Bell size={16}/> 감지 이벤트 <span className="count">{events.length}</span></h2><span className="muted">최신순 · 전체 영상 확인 필요 {connection === 'ready' ? summary?.pending : '—'}건</span></div><button className="outline" onClick={exportCsv}><Download size={15}/>CSV</button></div>
    <div className="event-filters">
      <label>날짜 (한국 시간)<input aria-label="이벤트 날짜" type="date" value={day} onChange={(e) => setDay(e.target.value)}/></label>
      <label>위반 종류<select value={equipment} onChange={(e) => setEquipment(e.target.value)}><option value="all">전체 종류</option><option value="NO-Hardhat">안전모 미착용 의심</option><option value="NO-Safety Vest">조끼 미착용 의심</option><option value="TEST_NO_HELMET">기존 테스트 기록</option></select></label>
      <label>확인 여부<select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">전체 상태</option><option value="pending">확인 필요</option><option value="reviewed">확인 완료</option></select></label>
    </div>
    {connection !== 'ready' && <div className="connection-note" role="status">{connection === 'loading' ? '이벤트 로딩 중' : '서버 연결 실패 · 마지막 조회 기록'}</div>}
    {connection === 'ready' && sustainedWarnings.length > 0 && <div className="sustained-warning-banner" role="alert">⚠ 현재 목록에 미확인 장기 미착용 경고 {sustainedWarnings.length}건이 있습니다. 감지 시각과 현장 상황을 확인해 주세요.</div>}
    <div className="event-list">
      {events.map((event) => <article key={event.id} className={`event-card ${event.reviewed ? 'reviewed' : 'unreviewed'}`}>
        <button className="event-open" onClick={() => {setSelected(event.id); setNewIds((previous) => {const next = new Set(previous); next.delete(event.id); return next;});}}>
          <div className="event-thumb"><Snapshot event={event}/></div>
          <div className="event-description"><div className="event-title">{(event.violation_types ?? [event.event_type]).map(eventName).join(' · ')} {newIds.has(event.id) && <b className="new-badge">새 감지</b>}</div><EventFacts event={event}/><span>{cameraLabel(event)} · 신뢰도 {event.confidence == null ? '없음' : `${(event.confidence*100).toFixed(1)}%`}</span><span className={event.reviewed ? 'signal-good' : 'signal-caution'}>{event.reviewed ? '✓ 확인 완료' : '⚠ 확인 필요'}</span></div>
        </button>
        {!event.reviewed && <button className="review" disabled={connection !== 'ready'} onClick={() => review(event.id)}><Check size={14}/>확인 완료 처리</button>}
      </article>)}
      {connection === 'ready' && events.length === 0 && <div className="state-empty">조건에 맞는 이벤트가 없습니다.</div>}
    </div>
    {canLoadMore && <button className="text-btn" onClick={loadMore}>이력 더 보기</button>}
    {selected != null && <div className="modal-backdrop" onClick={(event) => {if (event.target === event.currentTarget) setSelected(null);}}>
      <section className="event-detail panel" role="dialog" aria-modal="true" aria-labelledby="event-detail-title">
        <div className="section-title"><h2 id="event-detail-title">감지 상세 #{selected}</h2><button ref={closeRef} onClick={() => setSelected(null)} aria-label="상세 닫기"><X size={18}/></button></div>
        {detailError && <p role="alert">{detailError}</p>}
        {!detail && !detailError && <p>상세 정보 로딩 중</p>}
        {detail && <><div className="detail-snapshot"><Snapshot event={detail}/></div><div className="detail-info"><h3>{(detail.violation_types ?? [detail.event_type]).map(eventName).join(' · ')}</h3><p>{cameraLabel(detail)}</p><EventFacts event={detail} detailed/><p>신뢰도 {detail.confidence == null ? '없음' : `${(detail.confidence*100).toFixed(1)}%`} · {detail.model_name ?? '모델 정보 없음'}</p><p>{detail.review_status === 'reviewed' ? '✓ 확인 완료' : '⚠ 확인 필요'}</p><p className="muted">이벤트 시작 프레임의 인원입니다. 여러 보호구 미착용도 전체 인원에서는 한 명으로 계산합니다. 모델의 미착용 의심 감지이며 위반 확정이 아닙니다.</p>
          <div className="detail-actions"><button disabled={!detail.playable || !!detailError} onClick={async () => {if (await onJump(detail)) setSelected(null);}}><Play size={16}/>{detail.playable ? '해당 시점 영상 보기' : '재생 가능한 영상 없음'}</button><button disabled={detail.review_status === 'reviewed' || connection !== 'ready'} onClick={async () => {if (await review(detail.id)) setDetail({...detail, review_status:'reviewed'});}}><Check size={16}/>확인 완료</button></div></div></>}
      </section>
    </div>}
  </section>;
}
