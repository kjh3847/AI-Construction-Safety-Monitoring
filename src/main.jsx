import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ShieldCheck,
  LayoutDashboard,
  History,
  Settings,
  Camera,
  Bell,
  Upload,
  CircleHelp,
} from 'lucide-react';

import { cameras } from './data';
import MonitorPlayer, { stateLabel } from './MonitorPlayer';
import EventPanel from './EventPanel';
import './styles.css';
import './dashboard.css';

// Python 서버와 React를 같은 컴퓨터에서 실행하는 기준
const API_BASE_URL = 'http://127.0.0.1:8002';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options, signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function displayEvent(event) {
  return {
    ...event, time: event.created_at, camera: event.camera_name,
    equipment: event.event_type, reviewed: event.review_status === 'reviewed',
    worker: event.confidence == null ? '—' : `${(event.confidence * 100).toFixed(1)}%`,
  };
}

function read(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function App() {
  const [page, setPage] = useState('monitor');
  const [camera, setCamera] = useState(cameras[0]);

  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [connection, setConnection] = useState('loading');
  const [eventLimit, setEventLimit] = useState(100);
  const [day, setDay] = useState('');
  const [displayedFrame, setDisplayedFrame] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [jump, setJump] = useState(null);
  const [retention, setRetention] = useState(300);
  const [controlBusy, setControlBusy] = useState(false);

  const [filter, setFilter] = useState('all');
  const [equipment, setEquipment] = useState('all');
  const [video, setVideo] = useState(null);
  const [notice, setNotice] = useState('');

  const eventQuery = `/api/events?limit=${eventLimit}${page === 'monitor' ? `&camera_id=${camera.id}` : ''}${day ? `&day=${day}` : ''}${equipment !== 'all' ? `&event_type=${encodeURIComponent(equipment)}` : ''}${filter !== 'all' ? `&review_status=${filter}` : ''}`;

  useEffect(() => {
    if (analysis?.buffer) setRetention(analysis.buffer.retention_seconds);
  }, [analysis?.buffer?.retention_seconds]);

  const [seconds, setSeconds] = useState(() => {
    const value = Number(read('safety.seconds.v1', 5));
    return value >= 1 && value <= 60 ? value : 5;
  });

  const fileRef = useRef(null);
  const feedRef = useRef(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const syncFullscreen = () => {
      setIsFullscreen(Boolean(feedRef.current) && document.fullscreenElement === feedRef.current);
    };
    document.addEventListener('fullscreenchange', syncFullscreen);
    return () => document.removeEventListener('fullscreenchange', syncFullscreen);
  }, []);

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === feedRef.current) {
        await document.exitFullscreen();
      } else if (feedRef.current?.requestFullscreen) {
        await feedRef.current.requestFullscreen();
      } else {
        setNotice('이 브라우저에서는 전체화면 기능을 지원하지 않습니다.');
      }
    } catch {
      setNotice('전체화면을 열지 못했습니다. 브라우저에서 다시 시도해 주세요.');
    }
  }

  const isTestCamera = cameras.some((item) => item.id === camera.id);

  useEffect(() => {
    let active = true;
    let timer;
    setConnection('loading');
    async function refresh() {
      try {
        const [data, status] = await Promise.all([
          request(eventQuery), request(`/api/status?camera_id=${camera.id}`),
        ]);
        if (!active) return;
        setEvents(data.events.map(displayEvent));
        setSummary(data.summary);
        setAnalysis(status);
        setConnection('ready');
      } catch {
        if (active) setConnection('error');
      } finally {
        if (active) timer = setTimeout(refresh, 2000);
      }
    }
    refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [eventQuery, camera.id]);

  useEffect(() => {
    return () => {
      if (video) {
        URL.revokeObjectURL(video.url);
      }
    };
  }, [video]);

  useEffect(() => {
    if (!notice) return;

    const timer = setTimeout(() => setNotice(''), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  const pending = connection === 'ready' ? summary?.pending ?? 0 : 0;
  const historical = displayedFrame?.mode === 'past' || displayedFrame?.paused;
  const validFrame = connection === 'ready' && isTestCamera && analysis?.camera_id === camera.id && !video && displayedFrame &&
    (historical || (analysis?.state === 'running' && displayedFrame.recording_id === analysis.recording_id && Date.now()/1000 - displayedFrame.timestamp < 10));
  const connectionText = connection === 'loading' ? '데이터 로딩 중'
    : connection === 'error' ? '서버 연결 실패 · 마지막 조회 기록 (자동 재시도 중)'
    : 'DB 연결됨 · 2초마다 갱신';

  const shown = events.filter((event) => {
    const matchesStatus =
      filter === 'all' ||
      (filter === 'pending' ? !event.reviewed : event.reviewed);

    const matchesEquipment =
      equipment === 'all' || (event.violation_types ?? [event.equipment]).includes(equipment);

    return matchesStatus && matchesEquipment;
  });

  const titles = {
    monitor: '현장 모니터링',
    events: '이벤트 이력',
    settings: '모니터링 설정',
  };

  function changePage(nextPage) {
    // Viewing navigation does not stop server-side inference/recording.
    setPage(nextPage);
  }

  async function startAnalysis() {
    setVideo(null);
    setControlBusy(true);
    try {
      setAnalysis(await request(`/api/monitor/start?camera_id=${camera.id}`, {method:'POST'}));
      setNotice('서버 감지와 녹화를 시작했습니다. 화면 일시정지와 관계없이 계속됩니다.');
    } catch { setNotice('감지 시작 요청 실패 · 서버 연결을 확인하세요.'); }
    finally { setControlBusy(false); }
  }

  async function stopAnalysis() {
    setControlBusy(true);
    try {
      setAnalysis(await request(`/api/monitor/stop?camera_id=${camera.id}`, {method:'POST'}));
      setNotice('서버 감지·녹화 중단을 요청했습니다. 저장된 구간은 보관 기간 내 재생 가능합니다.');
    } catch { setNotice('감지 중단 요청 실패'); }
    finally { setControlBusy(false); }
  }

  function changeCamera(event) {
    const selected = cameras.find(
      (item) => item.id === event.target.value
    );

    if (!selected) return;

    setDisplayedFrame(null);
    setJump(null);
    setAnalysis(null);
    setConnection('loading');
    setVideo(null);
    setCamera(selected);
  }

  async function review(id) {
    try {
      await request(`/api/events/${id}`, { method: 'PATCH' });
      const data = await request(eventQuery);
      setEvents(data.events.map(displayEvent));
      setSummary(data.summary);
      setNotice('DB에 확인 상태를 저장했습니다.');
      return true;
    } catch {
      setNotice('확인 처리 결과를 조회하지 못했습니다. 서버 연결을 확인해 주세요.');
      return false;
    }
  }

  function upload(event) {
    const file = event.target.files?.[0];

    // 같은 파일을 다시 선택할 수 있도록 초기화
    event.target.value = '';

    if (!file) return;

    if (!file.type.startsWith('video/')) {
      setNotice('영상 파일을 선택해 주세요.');
      return;
    }

    setDisplayedFrame(null);

    setVideo({
      url: URL.createObjectURL(file),
      name: file.name,
    });

    setPage('monitor');
    setNotice('로컬 영상 미리보기입니다. YOLO 분석은 수행하지 않습니다.');
  }

  function exportCsv() {
    const rows = [
      ['ID', '감지/기록 시각 (UTC)', '카메라', '감지 클래스', '신뢰도', '확인 상태', '영상 위치 (초)', '당시 감지 인원', '해당 미착용 추정 인원', '전체 미착용 추정 인원', '사람 연결 불가 감지 수'],
      ...shown.map((event) => [
        event.id,
        event.detected_at ?? event.time,
        event.camera,
        (event.violation_types ?? [event.equipment]).join(' / '),
        event.worker,
        event.reviewed ? '확인 완료' : '확인 필요',
        event.video_seconds, event.person_count, event.event_person_count,
        event.noncompliant_person_count, event.unassigned_negative_count,
      ]),
    ];

    const csv = rows
      .map((row) =>
        row
          .map((value) => `"${String(value ?? '').replaceAll('"', '""')}"`)
          .join(',')
      )
      .join('\r\n');

    const blob = new Blob(['\uFEFF' + csv], {
      type: 'text/csv;charset=utf-8;',
    });

    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');

    link.href = url;
    link.download = '안전장비_감지이벤트.csv';

    document.body.appendChild(link);
    link.click();
    link.remove();

    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function saveSettings() {
    const value = Number(seconds);

    if (!Number.isInteger(value) || value < 1 || value > 60) {
      setNotice('1~60 사이의 정수를 입력해 주세요.');
      return;
    }

    try {
      localStorage.setItem('safety.seconds.v1', JSON.stringify(value));
      setNotice('브라우저에 저장했습니다. 분석 서버에는 아직 적용되지 않습니다.');
    } catch {
      setNotice('설정을 저장하지 못했습니다.');
    }
  }

  async function saveRetention() {
    try {
      const result = await request('/api/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({retention_seconds:Number(retention)})});
      setRetention(result.retention_seconds);
      setNotice('영상 보관 설정을 DB에 저장했습니다.');
    } catch { setNotice('보관 설정 저장 실패 · 30~1800초 범위와 서버 연결을 확인하세요.'); }
  }

  async function jumpToEvent(event) {
    try {
      const selected = cameras.find((item) => item.id === (event.camera_id ?? event.camera_name));
      if (!selected) throw new Error('연결된 영상 없음');
      const frame = await request(`/api/recordings/frame?camera_id=${selected.id}&recording_id=${event.recording_id}&frame_id=${event.frame_id}`);
      if (selected.id !== camera.id) { setDisplayedFrame(null); setAnalysis(null); setConnection('loading'); }
      setVideo(null); setCamera(selected); setPage('monitor');
      setJump({timestamp:frame.timestamp, nonce:Date.now()});
      return true;
    } catch { setNotice('재생 가능한 영상 없음 · 녹화 보관 범위를 벗어났습니다.'); return false; }
  }

  return (
    <div className={`app cctv ${expanded ? 'expanded' : ''}`}>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            changePage('monitor');
          }}
        >
          <ShieldCheck size={30} />
          <span>
            현장지킴
            <small>SITE SAFETY MONITOR</small>
          </span>
        </a>

        <div className="site-label">관리 현장</div>

        <div className="site-name">
          캡스톤 건설현장
          <span>안전관리 프로젝트</span>
        </div>

        <nav>
          {[
            ['monitor', LayoutDashboard, '현장 모니터링'],
            ['events', History, '이벤트 이력'],
            ['settings', Settings, '설정'],
          ].map(([key, Icon, label]) => (
            <button
              key={key}
              className={page === key ? 'active' : ''}
              onClick={() => changePage(key)}
              aria-current={page === key ? 'page' : undefined}
            >
              <Icon size={19} />
              {label}
              {key === 'events' && pending > 0 && <b>{pending}</b>}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <ShieldCheck size={22} />
          <p>
            안전은 확인에서 시작됩니다.
            <small>Capstone Design · 2026</small>
          </p>
        </div>
      </aside>

      <div className="workspace">
        <header>
          <span>
            캡스톤 건설현장
            <span className="slash">/</span>
            {titles[page]}
          </span>

          <div className="header-right">
            <span className="demo-dot">{connection !== 'ready' ? connectionText : `${analysis?.source_kind === 'camera' ? '실제 카메라' : '테스트 영상'} · ${stateLabel[analysis?.state] ?? '대기'}`}</span>

            <button
              className="icon-btn"
              aria-label="미확인 감지 알림 보기"
              onClick={() => {
                changePage('events');
                setFilter('pending');
              }}
            >
              <Bell size={20} />
              {pending > 0 && <i />}
            </button>

            <span className="avatar">관</span>
          </div>
        </header>

        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">SAFETY CONTROL CENTER</div>
              <h1>{titles[page]}</h1>
              <p>영상 관제 · 보호구 미착용 의심 감지</p>
            </div>

            <span className="date-label">{connectionText}</span>
          </div>

          <div className="demo-note">
            <CircleHelp size={17} />
            <span>
              화면 일시정지·과거 재생 중에도 서버 감지와 녹화는 계속됩니다. 미착용 감지는 위반 확정이 아닙니다.
            </span>
          </div>

          {page === 'settings' ? (
            <section className="panel settings">
              <h2>영상 보관 설정</h2>
              <p>최근 5분이 기본입니다. 실제 저장된 구간만 탐색할 수 있으며, 오래된 영상은 자동 정리됩니다.</p>
              <label htmlFor="retention">영상 보관 시간 (30~1800초)</label>
              <input id="retention" type="number" min="30" max="1800" value={retention} onChange={(event) => setRetention(event.target.value)}/>
              <button className="primary" onClick={saveRetention}>영상 보관 설정 저장</button>
              <p className="muted">용량 상한 256MB. 스냅샷은 최대 7일·512MB 보관합니다. 기간을 줄이면 이전 구간은 만료됩니다.</p>
              <h2>미착용 알림 기준</h2>
              <p>
                미착용 의심 상태가 지속되는 시간을 설정합니다.
                현재는 설정값 저장만 가능합니다.
              </p>

              <label htmlFor="seconds">지속 시간 (초)</label>

              <input
                id="seconds"
                type="number"
                min="1"
                max="60"
                value={seconds}
                onChange={(event) => setSeconds(event.target.value)}
              />

              <p className="muted">
                이 브라우저에만 저장됩니다. 실제 분석 서버의 알림 동작은
                변경되지 않습니다.
              </p>

              <button className="primary" onClick={saveSettings}>
                설정 저장
              </button>
            </section>
          ) : (
            <>
              {page === 'monitor' && <div className="stats">
                <Stat label={historical ? '재생 시점 감지 인원' : '현재 감지 인원'}
                  value={validFrame ? displayedFrame.person_count : '—'} unit="명"
                  detail={validFrame ? '해당 프레임 Person 검출 · 누적 인원 아님' : connection !== 'ready' ? connectionText : '감지 중인 영상이 없거나 수신 중단'} icon={<Camera/>}/>
                <Stat label={historical ? '재생 시점 미착용 인원 (추정)' : '보호구 미착용 인원 (추정)'}
                  value={validFrame ? displayedFrame.noncompliant_person_count ?? '—' : '—'} unit="명"
                  detail={!validFrame ? '영상 수신 후 표시' : displayedFrame.noncompliant_person_count == null ? '이 프레임의 사람 연결 정보 없음' : displayedFrame.unassigned_negative_count > 0 ? `사람 연결 불가 ${displayedFrame.unassigned_negative_count}건 · 인원 집계에서 제외` : '사람별 공간 연결 · 여러 보호구 미착용도 1명'} warning icon={<ShieldCheck/>}/>
                <Stat label="오늘 누적 위반 의심 이벤트" value={connection === 'ready' ? summary?.today ?? 0 : '—'} unit="건"
                  detail="전체 영상 · 한국 시간 기준 · 인원수 아님" warning icon={<Bell/>}/>
              </div>}
              <div className={`dashboard-grid ${page !== 'monitor' ? 'events-only' : ''}`}>
                {page === 'monitor' && <section className="panel monitor-panel">
                  <div className="section-title"><div><h2>현장 영상</h2><span className="muted">{camera.id} · {analysis?.source_kind === 'camera' ? '실제 카메라' : `${camera.name} (${camera.source})`}</span></div>
                    <select aria-label="카메라 선택" value={camera.id} onChange={changeCamera} disabled={controlBusy}>{cameras.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
                  </div>
                  <div className="player-shell" ref={feedRef}>
                    {video ? <div className="local-preview"><video controls src={video.url} onError={() => setNotice('영상을 재생하지 못했습니다.')}/><p>로컬 파일 미리보기 · AI 분석 없음</p><button onClick={toggleFullscreen}>전체화면</button></div> :
                      <MonitorPlayer key={camera.id} cameraId={camera.id} status={analysis} connection={connection} enabled={isTestCamera && analysis?.camera_id === camera.id} onFrame={setDisplayedFrame} jump={jump}
                        expanded={expanded} onExpand={() => setExpanded((value) => !value)} onFullscreen={toggleFullscreen} isFullscreen={isFullscreen}/>}
                  </div>
                  <div className="feed-footer">
                    <span className={analysis?.state === 'running' && connection === 'ready' ? 'signal-good' : 'signal-caution'}>{connection !== 'ready' ? connectionText : stateLabel[analysis?.state] ?? '대기'}</span>
                    <div className="capture-controls">
                      <button className="primary" onClick={startAnalysis} disabled={!isTestCamera || controlBusy || ['running','starting','stopping'].includes(analysis?.state)}>감지·녹화 시작</button>
                      <button className="danger-button" onClick={stopAnalysis} disabled={!isTestCamera || controlBusy || !['running','starting','stopping','disconnected'].includes(analysis?.state)}>감지·녹화 중단</button>
                      <button className="text-btn" onClick={() => fileRef.current?.click()}><Upload size={15}/>파일 미리보기</button>
                      {video && <button className="text-btn" onClick={() => setVideo(null)}>관제 영상으로 돌아가기</button>}
                    </div>
                  </div>
                  {analysis?.error && <p className="connection-note" role="alert">{analysis.error}</p>}
                  <div className="small-note">재생 화면과 인원은 같은 프레임 기준입니다. 미착용 인원은 사람·보호구 박스 위치를 연결한 추정치이며, 모호한 연결은 집계에서 제외합니다.</div>
                </section>}
                <div className="event-column">
                  <EventPanel events={shown} summary={summary} connection={connection} filter={filter} setFilter={setFilter}
                    equipment={equipment} setEquipment={setEquipment} day={day} setDay={setDay} review={review}
                    exportCsv={exportCsv} onJump={jumpToEvent} canLoadMore={events.length >= eventLimit && eventLimit < 1000}
                    loadMore={() => setEventLimit((value) => Math.min(value + 100, 1000))}/>
                </div>
              </div>
            </>
          )}

          <footer>
            현장지킴 · 안전장비 착용 모니터링
            <span>YOLOv8 기반 캡스톤 프로젝트</span>
          </footer>
        </main>
      </div>

      <input
        ref={fileRef}
        className="sr-only"
        type="file"
        accept="video/*"
        onChange={upload}
        aria-label="영상 파일 선택"
      />

      {notice && (
        <div className="toast" role="status">
          {notice}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, unit, detail, icon, warning }) {
  return (
    <section className={`stat ${warning ? 'stat-warning' : ''}`}>
      <div>
        <p>{label}</p>
        <strong>
          {value}
          <small>{unit}</small>
        </strong>
        <span>{detail}</span>
      </div>

      <div className="stat-icon">{icon}</div>
    </section>
  );
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
