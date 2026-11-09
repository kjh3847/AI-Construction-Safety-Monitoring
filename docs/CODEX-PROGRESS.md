# Codex 작업 진행 기록

## 목표와 보존 상태 (2026-11-10)

스마트폰 3대 → 인증 RTMPS → MediaMTX → 내부 RTSP AI 분석 / WebRTC 3분할 관제.
기존 YOLO, OSNet, 이벤트 DB, DVR, 직접 IP 카메라 입력을 보존한다.
이전 작업은 커밋 `3215e23`에 보존되어 있다. 이번 재개 시작 시 git status와 diff는 비어 있었다.
관련 로컬 서버 리스너는 없었으며 Docker 명령도 없었다. 데이터/설정 초기화 없이 진행한다.

## 이전 중단 지점

- MediaMTX v1.21.3, 카메라별 인증, 내부 RTSP 어댑터, WHEP 프록시, React WebRTC 구현까지 저장됨.
- `docs/media-integration-result.json`: 로컬 CA TLSv1.3 검증 성공, 이후 TimeoutError.
- `.local-run/media-integration-1794250576`에 이전 비공개 로그가 남아 있음.
- RTSP `_message()`가 첫 바이트를 버퍼 맨 뒤에 붙이는 오류 발견. 수정 후 재검증 진행.

## 우선순위와 완료 상태

- P0 완료: RTSP 응답 파싱 수정, 3채널 네이티브 통합 성공. Docker 엔진 실행은 외부 준비 필요.
- P1 로컬 완료: WebRTC/RTP 일치, AI 중단 시 영상 지속, 독립 재연결. 실제 YOLO/폰/Push 교차 ReID는 아래 미완료 항목 참고.
- P2 로컬 완료: 인증 권한/로그아웃/재연결, 프로세스 정리, 오래된 분석 표시 방지. 24시간·공중망 시험 미완료.
- P3 완료: Larix/AWS 가이드, 결과 보고서와 이 재개 기록.

## 이번 수정 파일

- `backend/rtsp_clock.py`: 수신 순서 보존.
- `src/MonitorPlayer.jsx`: AI 결과가 없어도 WebRTC 일시정지 허용.
- `src/MultiCameraMonitor.jsx`: 영상 연결과 AI 상태, 최근 수신 시각 구분.
- 이 문서: 재개 지점 보존.

전체 수정 파일과 이유는 [LIVE-STREAM-REPORT.md](LIVE-STREAM-REPORT.md)의 3절에 기록했다.

## 1차 재개 검증 완료

- RTSP 파서 수정 후 3채널 읽기 성공. Vite가 녹화 런타임 폴더를 감시하며 CPU/프록시 지연을 일으키던 문제에 대해 watch 제외 설정 추가.
- WebRTC 3분할, 원시 RTP 일치 텍스트, 일시정지/전체화면, 단일 송출 중지/재연결, AI 중단 중 영상 지속 확인.
- 잘못된 비밀번호, 정상 계정의 다른 CAM 게시, 비로그인 WHEP(프록시/직접) 거부 확인. 로그아웃 후 실제 미디어 세션 해제 확인.
- 제어 통신 실패 시 삭제되지 않은 시청 세션을 잊지 않고 재시도하도록 수정. 브라우저 재연결 경쟁/오래된 분석 표시 보완.
- 수신 시각을 촬영 시각으로 바꾸는 환경변수 우회 제거. Push 간 자동 ReID는 검증된 송신 시계 구현 전 비활성.
- Python 81개: 77 성공 / 4 skip (실제 YOLO 영상 1, PostgreSQL 3). Node 5개 성공, Vite build 성공, pip check 성공.
- MediaMTX v1.21.3 설정 검증 성공. Docker 엔진은 없지만 공식 standalone Compose v5.7.0을 별도 다운로드/SHA256 검증하여 합성 비밀값으로 병합 config --quiet 검증 성공. 이미지 빌드/컨테이너 실행과 구분한다.
- 최신 합성 통합 결과: `docs/media-integration-result.json` success=true. 5초 비교에서 WebRTC 각 15 FPS / 기존 바이너리 CAM-01 약 4.8 FPS. WebRTC 약 157 KB/s, 바이너리 약 91 KB/s. 표시 FPS 이득이지만 총 전송량 절감으로 보고하지 않음.
- 지터 버퍼 약 131ms. 실제 휴대폰 촬영→브라우저 전체 지연은 미측정. 실제 YOLO 성능 수치가 아님.
- `docs/PHONE-LIVE-STREAM-SETUP.md`, `docs/AWS-LIVE-STREAM-DEPLOY.md` 작성.

## 최종 재개 결과

- `tools/test_media_integration.py --real-app`: success=true. 실제 main:app, YOLO missing, OSNet ready, 3채널 영상/제어/인증/로그아웃 모두 성공. `docs/media-no-model-result.json` 참고.
- 이 시험의 초회 실패는 2초 고정 대기 후 송출 실패 판정의 경합이었다. 상태 기반 제한 시간 대기로 수정 후 통과.
- `tools/test_browser.py`: 기존 바이너리 3채널·독립 pause·전체화면·제어·이벤트 DVR·반응형 회귀 성공.
- 실제 기본 서버 브라우저 검증 성공: `.local-run/verification/resume-result.json`, `resumed-dashboard.png`.
- 기본 프론트엔드 http://127.0.0.1:5173 / 백엔드 http://127.0.0.1:8002 실행 유지. 실행 당시 launcher PID 33420 / 11364 (재개 시 PID를 신뢰해 종료하지 말고 manifest 소유권 검사).
- 로그인은 **로컬 데모로 대시보드 보기**. CAM-01 기존 직접 입력 설정/idle, CAM-02/03 미설정. 실제 카메라 영상과 best.pt 검증은 아직 없음.
- 합성 통합용 MediaMTX/FFmpeg/API/브라우저와 자식 프로세스는 정리했다. 관련 테스트 포트는 열려 있지 않다.
- 실제 OSNet 두 모델 특징 추론 성공. x0.25 약 12ms/crop, x1.0 약 475ms/crop. 실제 인물 데이터 정확도는 미검증.
- Node 24.22.2를 SHA256 확인 후 `.local-run/node-lts`에 비교용으로 다운로드했다. 시스템 Node 26은 그대로이며 기본 서버에서 정상 확인. 최초 지연을 Node 버전 문제로 단정하지 않는다.
- 변경은 미커밋 작업 트리에 보존. 이번 원격 push/AWS 변경 없음.
- 최종 git diff --check/UTF-8 확인 성공, 변경 파일 20개. 비밀파일이 변경 목록에 포함되지 않음을 확인했다.
- 기본 브라우저 자동 열기 명령은 실행 정책에 의해 차단됨(구체 사유 미제공). 우회하지 않았다. Playwright 검증은 성공했으므로 사용자는 위 URL을 직접 열면 된다.

현재 실행 중인 구현 작업은 없다. 남은 외부 환경/모델/시간 동기화 작업은 아래와 최종 보고서에 기록했다.
재개 시 결과 JSON, git diff, `.local-run/processes.json` 및 리스너를 먼저 확인한다.

## 다음 명령

프로젝트 루트 PowerShell:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH='C:\vscode\.playwright-browsers'
.\.venv\Scripts\python.exe tools/test_media_integration.py
.\.venv\Scripts\python.exe tools/test_media_integration.py --real-app
.\.venv\Scripts\python.exe -m unittest discover -s backend -p 'test_*.py'
node --test src/frameProtocol.test.js src/mediaClock.test.js
npm run build
.\.local-run\media-tools\mediamtx.exe --validate-conf=deploy/mediamtx.yml
.\.venv\Scripts\python.exe tools/run_local.py status
# 서버가 멈춘 경우
.\.venv\Scripts\python.exe tools/run_local.py start --mode demo
# 소유권이 확인된 로컬 서버만 종료
.\.venv\Scripts\python.exe tools/run_local.py stop
```

## 외부 환경에서 남은 확인

실제 best.pt 존재/YOLO 추론, 실제 스마트폰 Larix 3대, LTE/Wi-Fi 전환, AWS DNS/공인 TLS/ICE,
Docker 이미지 빌드 및 실행, PostgreSQL 통합, 실제 인물 ReID 정확도 및 24시간 안정성은 별도 검증 필요.
검증된 송신 촬영 시계 파서 및 그 시계로 Push 카메라 간 ReID 연결을 구현하는 개발도 남아 있다.
SRT와 TURN은 현재 활성화/구현 완료 상태가 아니다.
합성 영상/합성 검출 fixture를 실제 카메라 또는 YOLO 검증으로 보고하지 않는다.
AWS 리소스 생성 및 원격 push는 하지 않는다. 인증정보는 Git 제외 파일에만 저장한다.
