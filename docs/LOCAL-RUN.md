# Windows 로컬 실행 및 실제 브라우저 검증

> 재개 후 최신 상태: [CODEX-PROGRESS.md](CODEX-PROGRESS.md), [LIVE-STREAM-REPORT.md](LIVE-STREAM-REPORT.md).
> 아래 최초 실행 기록 이후 CAM-01 직접 입력 설정이 추가되었으며 해당 설정은 보존했다.
> 기본 대시보드와 합성 MediaMTX 통합 시험은 서로 다른 포트/DB를 사용한다. 기본 화면에 합성 영상을 자동 표시하지 않는다.

2026-11-10에 기존 변경 사항을 유지하며 실행했습니다. AWS 배포, GitHub push, 운영 DB 접속은 수행하지 않았습니다.

## 접속

- 프론트엔드: http://127.0.0.1:5173
- 백엔드: http://127.0.0.1:8002
- 상태 확인: http://127.0.0.1:8002/health
- 런타임 모드/모델 상태: http://127.0.0.1:8002/api/runtime

로그인 화면에서 **로컬 데모로 대시보드 보기**를 누릅니다. 비밀번호를 입력할 필요가 없습니다.
이 경로는 기존 회사 계정 로그인이 아닌, 명시적으로 구분된 로컬 데모 세션입니다.
상단 LOCAL DEMO 표시와 세 카메라의 ‘연결 안 됨’ 상태를 확인할 수 있습니다.
가짜 영상·사람·이벤트·탐지 결과는 만들지 않았습니다.

## 실행 상태와 환경

| 항목 | 실제 확인한 결과 |
|---|---|
| Windows | Windows 11, build 26200 |
| Python | 프로젝트 `.venv`, Python 3.14.5 |
| Node/npm | Node 26.13.0 / npm 11.20.0 |
| 프론트엔드 | Vite 실제 HTTP 접속 성공, 127.0.0.1:5173 |
| 백엔드 | ASGI `backend/main.py:app`, Uvicorn, 127.0.0.1:8002 |
| YOLO | `best.pt` 없음. 미로드. 실제 보호구 검출은 미검증 |
| ReID | `models/osnet_x0_25.onnx` 존재, 현재 서버에서 ONNX Runtime 로드 성공 |
| 계정 PostgreSQL | `.env`/DATABASE_URL 없음. 기존 계정 로그인은 미검증 |
| 로컬 데모 DB | 별도 SQLite 세션/이벤트/추적 DB 연결 성공 |
| CAM-01/02/03 | 입력 주소·기존 시험 영상 없음. 모두 미연결 |
| 브라우저 | Chromium에서 실제 Vite/API/세션/WebSocket 검증 성공. 요청 가로채기 없음 |

FastAPI 0.162.2, Uvicorn 0.54.0, Ultralytics 8.4.152, PyTorch 2.15.0,
ONNX Runtime 1.31.1, Playwright 1.64.1 및 기존 의존성이 설치되어 있었습니다.
`pip check`는 충돌 없이 통과했습니다. 추가 패키지 설치는 필요하지 않았습니다.
시작 전 5173/8002 등 후보 포트는 socket bind로 확인했고 기존 프로세스를 종료하지 않았습니다.

## 다시 실행 / 종료

프로젝트 루트에서 실행합니다. Python 명령은 PowerShell 스크립트 실행 정책의 영향을 받지 않습니다.

```powershell
cd C:\vscode\AI-Construction-Safety-Monitoring
.\.venv\Scripts\python.exe tools/run_local.py start --mode demo
.\.venv\Scripts\python.exe tools/run_local.py status
# 확인을 마친 뒤에만 실행
.\.venv\Scripts\python.exe tools/run_local.py stop
```

PowerShell 래퍼도 제공합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Local.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Local.ps1 -Action status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Local.ps1 -Action stop
```

실행기는 숨겨진 별도 프로세스로 서버를 유지하고 `.local-run/processes.json`에 소유 정보를 기록합니다.
종료할 때 PID, 생성 시각, 실행 명령, 작업 경로가 모두 일치하는 프로세스와 그 자식만 종료합니다.
점유 포트의 다른 프로세스를 강제로 종료하지 않습니다. 기본 포트가 사용 중이면 빈 포트를 선택해 실제 URL을 출력합니다.
로그는 `.local-run/backend.log`, `.local-run/frontend.log`입니다.

## 설정과 데이터 분리

- 로컬 데모 설정: Git에서 제외된 `.env.local-run`.
- 카메라 입력: `CAMERA_01_SOURCE`, `CAMERA_02_SOURCE`, `CAMERA_03_SOURCE`.
- 학습 모델: `MODEL_PATH=backend/best.pt`에 기존 학습 가중치를 준비합니다.
- ReID 모델: `REID_MODEL_PATH=models/osnet_x0_25.onnx`.
- 데모 데이터: `.local-run/demo/events.sqlite3`, `sessions.sqlite3`, `recordings/`.
- 기존 `.env`, `backend/safety.db`, 운영 계정·이벤트 데이터는 변경하거나 초기화하지 않습니다.
- 설정을 바꾼 후에는 위 명령으로 이 실행기가 띄운 서버만 중지하고 다시 실행합니다.

데모는 `LOCAL_DEMO_ENABLED=true`를 명시적으로 설정한 경우에만 동작합니다.
계정 DATABASE_URL이 있거나 데이터 경로가 `.local-run/demo` 밖이면 시작을 거부합니다.
실제 HTTP peer와 Host가 loopback인지 확인하고, POST/PATCH Origin을 검사합니다.
세션 쿠키도 운영용 `safety_session`과 다른 `safety_local_demo`이며 토큰 해시만 로컬에 저장합니다.
로그아웃/만료 후에는 API 접근이 거부됩니다. 운영 인증 라우터에는 데모 로그인 endpoint가 없습니다.

기존 계정 인증을 실제로 쓰려면 정상 PostgreSQL 설정을 `.env`에 준비하고 서버를 중지한 뒤 실행합니다.

```powershell
.\.venv\Scripts\python.exe tools/run_local.py start --mode configured
```

이 모드는 기존 계정/세션 인증을 사용합니다. 기존 계정을 생성·삭제하거나 비밀번호를 바꾸지 않습니다.
실행기는 로컬 HTTP origin과 secure-cookie 설정을 자식 프로세스에만 적용하고 원본 `.env`를 덮어쓰지 않습니다.

PC는 카메라 앱의 실제 HTTP/RTSP 스트림을 **밖으로 요청**하므로 API를 127.0.0.1에 바인딩해도 카메라 수신은 가능합니다.
다만 스마트폰과 PC의 통신 경로, 앱 실행 상태, Wi-Fi 단말 격리, 방화벽과 실제 스트림 경로는 현장에서 확인해야 합니다.
입력 주소가 제공되지 않아 실제 스마트폰 연결은 검사하지 않았습니다. 임의의 카메라 주소는 설정하지 않았습니다.

## 발견한 오류와 수정

1. 계정 DB가 없으면 기존 lifespan 초기화가 실패하여 서버가 시작되지 않았습니다.
   운영 인증과 데이터 경로를 분리한 loopback 전용 데모 경로를 추가했습니다.
2. 실제 브라우저에서 Google Fonts 요청이 차단되어 콘솔 오류가 발생했습니다.
   `src/styles.css`의 외부 import를 제거하고 기존 Windows 한글 글꼴 fallback을 사용했습니다.
3. WebSocket peer가 이미 종료된 뒤 마지막 close에서 WebSocketDisconnect가 서버 오류로 기록되었습니다.
   정상 종료로 처리하고 회귀 검사를 추가했습니다.
4. 입력이 없는데 영상 버퍼 준비로만 표시되던 상태를 ‘연결 안 됨’으로 명시했습니다.
   미설정 소스에는 영상 연결을 열지 않고, 전체 시작 요청도 불필요한 worker를 만들지 않습니다.
5. 실제 캡처에서 데모 표시 일부가 고정 sidebar에 가려져 여백을 조정했습니다.

이번 실행 작업에서 수정/추가한 파일:

- `backend/local_demo.py`, `backend/main.py`, `backend/account_server.py`, `backend/monitor.py`
- `backend/test_local_demo.py`, `backend/test_live_api.py`
- `src/LoginPage.jsx`, `src/main.jsx`, `src/MonitorPlayer.jsx`, `src/MultiCameraMonitor.jsx`
- `src/styles.css`, `src/dashboard.css`, `vite.config.js`
- `tools/run_local.py`, `tools/check_running_local.py`, `tools/test_browser.py`, `Start-Local.ps1`
- `.env.example`, `.gitignore`, README 및 운영 안내 링크, 이 문서

이전 멀티 카메라/ReID/이벤트/녹화 구현 파일은 유지합니다.

## 검사 결과와 실제 증거

- 백엔드: **71개 중 67개 통과, 4개 건너뜀**.
  건너뛴 항목은 실제 best.pt/시험 영상 1개와 별도 PostgreSQL 테스트 DB 3개입니다.
- `npm.cmd run build`, Node 전송/텍스트 테스트 2개, `compileall`, `pip check`, `git diff --check` 통과.
- 이전 합성 영상 브라우저 회귀 검사도 통과해 개별 일시정지·카메라 간 프레임 분리·과거 영상 이동을 유지함을 확인했습니다.
- 실제 서버 브라우저 검사: 로그인 화면, 명시적 데모 진입, 3개 카메라 동시 표시, 미연결 상태,
  전체화면 진입/종료, 개별 API 대상 분리, 전체 제어, 이벤트/설정 이동, 반응형,
  실제 인증 WebSocket handshake/종료, 로그아웃 후 API 차단을 통과했습니다.
- 실제 검사에서 JavaScript 오류 0건, 콘솔 오류 0건, 외부 요청 0건입니다.
  초기/로그아웃 후 `/api/auth/me`의 예상된 401은 정상적인 세션 확인 응답으로 구분했습니다.
- `.local-run/verification/login.png`, `dashboard.png`, `result.json`에 실제 화면/결과를 저장했습니다.
  이 파일들과 실행 로그, 데모 DB는 Git에서 제외됩니다.

카메라·best.pt가 없으므로 실제 영상의 보호구 검출, 텍스트 오버레이의 현장 결과,
실제 녹화/과거 조회, 기존 PostgreSQL 계정 로그인, 실제 ReID 동일인 매칭 정확도는 성공으로 판정하지 않았습니다.
계정 DB와 입력을 준비하면 같은 시스템에서 해당 검증을 이어갈 수 있습니다.
