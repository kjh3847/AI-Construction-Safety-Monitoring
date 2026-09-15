import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ShieldCheck,
  LayoutDashboard,
  History,
  Settings,
  Camera,
  Bell,
  ArrowUpRight,
  Download,
  Upload,
  Check,
  Video,
  CircleHelp,
  Maximize,
  Minimize,
} from 'lucide-react';

import { cameras, initialEvents } from './data';
import './styles.css';

// Python 서버와 React를 같은 컴퓨터에서 실행하는 기준
const API_BASE_URL = 'http://127.0.0.1:8000';

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

  const [events, setEvents] = useState(() => {
    const saved = read('safety.events.v1', initialEvents);

    const valid =
      Array.isArray(saved) &&
      saved.every(
        (event) =>
          event &&
          typeof event.id === 'string' &&
          typeof event.time === 'string' &&
          typeof event.equipment === 'string'
      );

    return valid ? saved : initialEvents;
  });

  const [filter, setFilter] = useState('all');
  const [equipment, setEquipment] = useState('all');
  const [video, setVideo] = useState(null);
  const [notice, setNotice] = useState('');

  // 주소가 있으면 분석 영상을 표시하고, 없으면 연결 중지
  const [streamUrl, setStreamUrl] = useState('');
  const [streamError, setStreamError] = useState('');

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

  const isTestCamera = camera.id === cameras[0].id;

  useEffect(() => {
    try {
      localStorage.setItem('safety.events.v1', JSON.stringify(events));
    } catch {
      setNotice('브라우저 저장 공간을 사용할 수 없습니다.');
    }
  }, [events]);

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

  const pending = events.filter((event) => !event.reviewed).length;

  const shown = events.filter((event) => {
    const matchesStatus =
      filter === 'all' ||
      (filter === 'pending' ? !event.reviewed : event.reviewed);

    const matchesEquipment =
      equipment === 'all' || event.equipment === equipment;

    return matchesStatus && matchesEquipment;
  });

  const titles = {
    monitor: '현장 모니터링',
    events: '이벤트 이력',
    settings: '모니터링 설정',
  };

  function changePage(nextPage) {
    // 페이지를 떠나면 영상 연결 종료
    setStreamUrl('');
    setStreamError('');
    setPage(nextPage);
  }

  function startAnalysis() {
    setVideo(null);
    setStreamError('');

    // 매번 다른 주소를 사용해 이전 이미지 캐시 방지
    setStreamUrl(`${API_BASE_URL}/video?session=${Date.now()}`);

    setNotice('분석 영상을 요청했습니다. 첫 화면까지 잠시 기다려 주세요.');
  }

  function stopAnalysis() {
    setStreamUrl('');
    setStreamError('');
  }

  function handleStreamError() {
    setStreamUrl('');
    setStreamError(
      '분석 연결이 끝났거나 영상을 불러오지 못했습니다. ' +
      'FastAPI 터미널의 오류와 다른 분석 영상 탭이 열려 있는지 확인한 뒤 다시 시작해 주세요.'
    );
  }

  function changeCamera(event) {
    const selected = cameras.find(
      (item) => item.id === event.target.value
    );

    if (!selected) return;

    stopAnalysis();
    setVideo(null);
    setCamera(selected);
  }

  function review(id) {
    setEvents((previous) =>
      previous.map((event) =>
        event.id === id ? { ...event, reviewed: true } : event
      )
    );

    setNotice('예시 이벤트를 확인 처리했습니다.');
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

    stopAnalysis();

    setVideo({
      url: URL.createObjectURL(file),
      name: file.name,
    });

    setPage('monitor');
    setNotice('로컬 영상 미리보기입니다. YOLO 분석은 수행하지 않습니다.');
  }

  function exportCsv() {
    const rows = [
      ['ID', '발생 시각', '카메라', '장비', '작업자', '확인 상태'],
      ...shown.map((event) => [
        event.id,
        event.time,
        event.camera,
        event.equipment,
        event.worker,
        event.reviewed ? '확인 완료' : '확인 필요',
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
    link.download = '안전장비_예시이벤트.csv';

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

  return (
    <div className="app">
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
            <span className="demo-dot">영상 분석 테스트</span>

            <button
              className="icon-btn"
              aria-label="미확인 예시 알림 보기"
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
              <p>작업자의 안전장비 착용 상태를 한눈에 확인하세요.</p>
            </div>

            <span className="date-label">프로젝트 테스트 화면</span>
          </div>

          <div className="demo-note">
            <CircleHelp size={17} />
            <span>
              분석 시작 시 서버의 test.mp4를 YOLO로 분석합니다.
              인원 통계·착용 상태·이벤트 DB는 아직 연결 전입니다.
            </span>
          </div>

          {page === 'settings' ? (
            <section className="panel settings">
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
              {page === 'monitor' && (
                <>
                  <div className="stats">
                    <Stat
                      label="탐지된 작업자"
                      value="—"
                      detail="인원 데이터 연결 전"
                      icon={<Camera />}
                    />

                    <Stat
                      label="안전장비 착용"
                      value="—"
                      detail="착용 상태 데이터 연결 전"
                      icon={<ShieldCheck />}
                    />

                    <Stat
                      label="확인이 필요한 예시 이벤트"
                      value={pending}
                      unit="건"
                      detail="실제 분석 결과가 아닌 예시 이력"
                      warning
                      icon={<Bell />}
                    />
                  </div>

                  <div className="monitor-grid">
                    <section className="panel monitor-panel">
                      <div className="section-title">
                        <div>
                          <h2>현장 영상</h2>
                          <span className="muted">
                            {camera.id} · {camera.name}
                          </span>
                        </div>

                        <label className="sr-only" htmlFor="camera">
                          카메라 선택
                        </label>

                        <select
                          id="camera"
                          value={camera.id}
                          onChange={changeCamera}
                        >
                          {cameras.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="feed" ref={feedRef}>
                        <button
                          type="button"
                          className="feed-fullscreen-button"
                          onClick={toggleFullscreen}
                          aria-label={isFullscreen ? '전체화면 종료' : '영상 전체화면'}
                          title={isFullscreen ? '전체화면 종료 (Esc)' : '영상 전체화면'}
                          aria-pressed={isFullscreen}
                        >
                          {isFullscreen ? <Minimize size={18} /> : <Maximize size={18} />}
                          <span>{isFullscreen ? '전체화면 종료' : '전체화면'}</span>
                        </button>
                        {video ? (
                          <video
                            controls
                            src={video.url}
                            onError={() =>
                              setNotice(
                                '영상을 재생하지 못했습니다. 브라우저에서 지원하는 MP4 파일을 사용해 주세요.'
                              )
                            }
                          />
                        ) : streamUrl ? (
                          <>
                            <img
                              key={streamUrl}
                              src={streamUrl}
                              alt="YOLO 분석 영상 수신 중"
                              onError={handleStreamError}
                            />
                            <span className="feed-tag">
                              YOLO · 시험 영상 분석
                            </span>
                          </>
                        ) : (
                          <div className="empty-feed">
                            <Video size={40} />

                            <h3>
                              {streamError
                                ? '분석 연결 확인 필요'
                                : isTestCamera
                                  ? '시험 영상 분석 준비'
                                  : '연결된 카메라가 없습니다'}
                            </h3>

                            <p
                              style={{
                                padding: '0 20px',
                                textAlign: 'center',
                              }}
                            >
                              {streamError ||
                                (isTestCamera
                                  ? '아래 분석 시작 버튼을 눌러 주세요.'
                                  : '첫 번째 카메라에서 시험 영상을 분석할 수 있습니다.')}
                            </p>
                          </div>
                        )}
                      </div>

                      <div
                        className="feed-footer"
                        style={{ flexWrap: 'wrap' }}
                      >
                        <span>
                          {video
                            ? '로컬 미리보기 · AI 분석 없음'
                            : streamUrl
                              ? '서버 test.mp4 분석 · CPU 속도에 따라 지연 가능'
                              : '분석 서버: 127.0.0.1:8000'}
                        </span>

                        {streamUrl ? (
                          <button
                            className="text-btn"
                            onClick={stopAnalysis}
                          >
                            분석 중지
                          </button>
                        ) : isTestCamera ? (
                          <button
                            className="text-btn"
                            onClick={startAnalysis}
                          >
                            <Video size={16} />
                            분석 시작
                          </button>
                        ) : null}

                        <button
                          className="text-btn"
                          onClick={() => fileRef.current?.click()}
                        >
                          <Upload size={16} />
                          파일 미리보기
                        </button>

                        {video && (
                          <button
                            className="text-btn"
                            onClick={() => setVideo(null)}
                          >
                            미리보기 닫기
                          </button>
                        )}
                      </div>

                      <div className="small-note">
                        영상이 끝나면 분석 중지를 누른 뒤 잠시 기다렸다가
                        다시 시작하세요. 별도의 /video 탭은 닫아 주세요.
                      </div>
                    </section>

                    <section className="panel status-panel">
                      <div className="section-title">
                        <h2>작업자 착용 상태</h2>
                        <span className="tag">연결 예정</span>
                      </div>

                      <div className="state-empty">
                        개별 작업자의 착용 상태 데이터는
                        <br />
                        아직 연결되지 않았습니다.
                      </div>

                      <div className="status-note">
                        <ShieldCheck size={26} />
                        <p>
                          현재는 영상 안의 탐지 박스로
                          <br />
                          모델 분석 결과를 확인할 수 있습니다.
                        </p>
                      </div>

                      <div className="small-note">
                        미착용 지속 시간 판단과 이벤트 저장은
                        <br />
                        다음 단계에서 연결할 예정입니다.
                      </div>
                    </section>
                  </div>
                </>
              )}

              <section className="panel event-panel">
                <div className="section-title">
                  <div>
                    <h2>
                      예시 이벤트
                      <span className="count">{shown.length}</span>
                    </h2>

                    <span className="muted">
                      아래 기록은 예시입니다. 실제 YOLO 결과와 DB는 연결 전입니다.
                    </span>
                  </div>

                  <button className="outline" onClick={exportCsv}>
                    <Download size={16} />
                    CSV 내보내기
                  </button>
                </div>

                <div className="filters">
                  <div className="tabs">
                    {[
                      ['all', '전체'],
                      ['pending', '확인 필요'],
                      ['reviewed', '확인 완료'],
                    ].map(([value, label]) => (
                      <button
                        key={value}
                        className={filter === value ? 'selected' : ''}
                        onClick={() => setFilter(value)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  <label className="sr-only" htmlFor="equipment">
                    장비 종류
                  </label>

                  <select
                    id="equipment"
                    value={equipment}
                    onChange={(event) => setEquipment(event.target.value)}
                  >
                    <option value="all">모든 안전장비</option>
                    <option value="안전모">안전모</option>
                    <option value="안전조끼">안전조끼</option>
                  </select>
                </div>

                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>발생 시각</th>
                        <th>카메라</th>
                        <th>작업자</th>
                        <th>이벤트</th>
                        <th>상태</th>
                        <th>확인</th>
                      </tr>
                    </thead>

                    <tbody>
                      {shown.map((event) => (
                        <tr key={event.id}>
                          <td>{event.time.replace('T', ' ')}</td>
                          <td>{event.camera}</td>
                          <td>{event.worker}</td>

                          <td>
                            <span className="event-dot" />
                            {event.equipment} 미착용 의심
                          </td>

                          <td>
                            <span
                              className={
                                event.reviewed
                                  ? 'badge done'
                                  : 'badge warning'
                              }
                            >
                              {event.reviewed ? '확인 완료' : '확인 필요'}
                            </span>
                          </td>

                          <td>
                            <button
                              className="review"
                              disabled={event.reviewed}
                              onClick={() => review(event.id)}
                              aria-label={`${event.id} 확인 처리`}
                            >
                              {event.reviewed ? (
                                <Check size={16} />
                              ) : (
                                <>
                                  확인
                                  <ArrowUpRight size={14} />
                                </>
                              )}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {shown.length === 0 && (
                    <div className="state-empty">
                      조건에 맞는 이벤트가 없습니다.
                    </div>
                  )}
                </div>
              </section>
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