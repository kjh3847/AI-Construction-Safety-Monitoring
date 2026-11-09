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
import MultiCameraMonitor from './MultiCameraMonitor';
import EventPanel from './EventPanel';
import LoginPage from './LoginPage';
import AccountPage from './AccountPage';
import ProfileMenu from './ProfileMenu';
import { API_BASE, accountRequest } from './api';
import './styles.css';
import './dashboard.css';

// Python 서버와 React를 같은 컴퓨터에서 실행하는 기준
const API_BASE_URL = API_BASE;

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options, credentials: 'include', signal: AbortSignal.timeout(5000),
  });
  if (response.status === 401) window.dispatchEvent(new Event('session-expired'));
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

function App({onLogout, user}) {
  const [page, setPage] = useState('monitor');

  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [totals,setTotals] = useState({people:0,violations:0,active:0});
  const [connection, setConnection] = useState('loading');
  const [eventLimit, setEventLimit] = useState(100);
  const [day, setDay] = useState('');
  const [jump, setJump] = useState(null);
  const [retention, setRetention] = useState(30 * 86400);

  const [filter, setFilter] = useState('all');
  const [equipment, setEquipment] = useState('all');
  const [video, setVideo] = useState(null);
  const [notice, setNotice] = useState('');

  const eventQuery = `/api/events?limit=${eventLimit}${day ? `&day=${day}` : ''}${equipment !== 'all' ? `&event_type=${encodeURIComponent(equipment)}` : ''}${filter !== 'all' ? `&review_status=${filter}` : ''}`;

  useEffect(() => {
    let active=true;
    request('/api/status').then(s => {if(active) setRetention(s.buffer.retention_seconds);}).catch(()=>{});
    return () => {active=false;};
  },[]);

  const [seconds, setSeconds] = useState(() => {
    const value = Number(read('safety.seconds.v1', 5));
    return value >= 1 && value <= 60 ? value : 5;
  });

  const fileRef = useRef(null);
  useEffect(() => {
    let active = true;
    let timer;
    setConnection('loading');
    async function refresh() {
      try {
        const data = await request(eventQuery);
        if (!active) return;
        setEvents(data.events.map(displayEvent));
        setSummary(data.summary);
        setConnection('ready');
      } catch {
        if (active) setConnection('error');
      } finally {
        if (active) timer = setTimeout(refresh, 2000);
      }
    }
    refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [eventQuery]);

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
    } catch { setNotice('보관 설정 저장 실패 · 1~30일 범위와 서버 연결을 확인하세요.'); }
  }

  async function jumpToEvent(event) {
    try {
      const selected = cameras.find((item) => item.id === (event.camera_id ?? event.camera_name));
      if (!selected) throw new Error('연결된 영상 없음');
      const frame = await request(`/api/recordings/frame?camera_id=${selected.id}&recording_id=${event.recording_id}&frame_id=${event.frame_id}`);
      setVideo(null); setPage('monitor');
      setJump({timestamp:frame.timestamp, cameraId:selected.id, nonce:Date.now()});
      return true;
    } catch { setNotice('재생 가능한 영상 없음 · 녹화 보관 범위를 벗어났습니다.'); return false; }
  }

  return (
    <div className="app cctv">
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
            <span className="demo-dot">{connection !== 'ready' ? connectionText : `3대 동시 관제 · 실시간 수신 ${totals.active}/3대`}</span>

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

            <ProfileMenu onLogout={onLogout} user={user}/>
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
              <p>기본 보관 기간은 30일입니다. 서버를 재시작해도 파일은 유지되며, 보관 기간이 지난 영상은 자동 정리됩니다.</p>
              <label htmlFor="retention">영상 보관 기간 (1~30일)</label>
              <input id="retention" type="number" min="1" max="30" step="1" value={retention / 86400} onChange={(event) => setRetention(Number(event.target.value) * 86400)}/>
              <button className="primary" onClick={saveRetention}>영상 보관 설정 저장</button>
              <p className="muted">감지 영상 프레임과 스냅샷에 같은 보관 기간을 적용합니다. 기존 용량 상한에 따른 조기 삭제는 하지 않습니다. 디스크 여유 공간이 1GB 미만이면 새 녹화를 중단합니다. 기간을 줄이면 이전 구간은 만료됩니다.</p>
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
              {page === 'monitor' && <>
                <div className="stats">
                  <Stat label="현재 감지 인원 합계" value={totals.active ? totals.people : '—'} unit="명" detail={`실시간 수신 ${totals.active}/3대 · 카메라별 검출 합계`} icon={<Camera/>}/>
                  <Stat label="현재 미착용 추정 인원 합계" value={totals.active ? totals.violations : '—'} unit="명" detail="각 카메라의 명시적 미착용 증거 기준" warning icon={<ShieldCheck/>}/>
                  <Stat label="오늘 누적 이벤트" value={summary?.today ?? '—'} unit="건" detail="전체 카메라 · 한국 시간 기준" warning icon={<Bell/>}/>
                </div>
                <MultiCameraMonitor jump={jump} onTotals={setTotals}/>
                <button className="text-btn" onClick={() => fileRef.current?.click()}><Upload size={15}/>파일 미리보기</button>
                {video && <div className="local-preview"><video controls src={video.url}/><p>로컬 파일 미리보기 · AI 분석 없음</p><button onClick={() => setVideo(null)}>미리보기 닫기</button></div>}
              </>}
              <EventPanel events={shown} summary={summary} connection={connection} filter={filter} setFilter={setFilter}
                equipment={equipment} setEquipment={setEquipment} day={day} setDay={setDay} review={review}
                exportCsv={exportCsv} onJump={jumpToEvent} canLoadMore={events.length >= eventLimit && eventLimit < 1000}
                loadMore={() => setEventLimit((value) => Math.min(value + 100, 1000))}/>

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

function Root() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [runtime,setRuntime] = useState(null);
  useEffect(() => {
    const expire = () => setUser(null);
    window.addEventListener('session-expired', expire);
    accountRequest('/api/auth/me').then(setUser).catch(e => setMessage(e.message)).finally(() => setLoading(false));
    accountRequest('/api/runtime').then(setRuntime).catch(()=>{});
    return () => window.removeEventListener('session-expired', expire);
  }, []);
  async function logout() {
    try { await accountRequest('/api/auth/logout', {method:'POST'}); setMessage(''); setUser(null); return true; }
    catch(e) {setMessage(e.message); return false;}
  }
  if (loading) return <div className="login-page">로그인 상태 확인 중…</div>;
  if (!user || user.must_change_password) return <LoginPage user={user} localDemo={runtime?.local_demo} onLogin={result=>{setMessage('');setUser(result);}} onLogout={()=>setUser(null)}/>;
  if (window.location.pathname === '/admin/accounts') {
    if (user.role !== 'system') return <div className="login-page"><p>시스템팀 권한이 필요합니다. <a href="/">대시보드로 이동</a></p></div>;
    return <AccountPage onLogout={logout}/>;
  }
  return <>{runtime?.local_demo && <div className="local-demo-banner" role="status">LOCAL DEMO · 운영 계정과 분리된 로컬 관제 화면 · YOLO {runtime.yolo_state === 'missing' ? '모델 없음' : runtime.yolo_state}</div>}{user.role === 'system' && <div className="session-bar"><span>{user.employee_id}</span><a href="/admin/accounts">관리자 계정 관리</a></div>}<App onLogout={logout} user={user}/></>;
}
createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
