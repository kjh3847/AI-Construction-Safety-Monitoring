# 스마트폰 스트리밍 개발 재개 보고 (2026-11-10)

## 1. 이전 중단 상태

커밋 `3215e23`에 기존 개발 75개 파일 변경이 보존되어 있었다. 재개 당시 git status/diff는 비어 있었고
기본 서버 및 통합 시험 리스너가 없었다. 이전 통합 결과는 로컬 CA TLSv1.3 성공 이후 브라우저 시간 초과였다.
기존 DB, `.env.local-run`의 CAM-01 설정, 모델 파일, 녹화 자료를 삭제하거나 초기화하지 않았다.

## 2. 이번 완료한 개발

- RTSP 패킷 읽기에서 첫 바이트 순서가 뒤바뀌던 오류 수정. 3개 경로 모두 실제 H.264 디코딩 성공.
- Vite가 생성되는 녹화/runtime 파일을 감시하지 않도록 제외하여 개발 서버 부하/프록시 지연 완화.
- WebRTC 연결 시도 간 경쟁, 취소, 연결 시간 제한, 오래된 AI 표시 보완.
- AI 분석 프레임이 없어도 영상 일시정지 허용. 기존 바이너리 FPS와 WebRTC FPS 표시 중복 제거.
- 영상 연결/최근 수신/AI 상태 분리 표시.
- 세션 삭제 통신 실패 시 로그아웃된 시청자를 잊지 않고 재시도하도록 변경.
- 환경변수만으로 서버 수신 시각을 신뢰하는 ReID 우회 제거. 실제 송신 시각 검증 전 Push 자동 교차 매칭 중지.
- 네이티브 통합 시험을 채널별 인증, 로그아웃 미디어 종료, 재연결, 실제 모델 부재 상황까지 확대.

## 3. 수정 파일 목록

| 파일 | 변경 이유 |
|---|---|
| `backend/rtsp_clock.py` | 수신 바이트 순서 보존 |
| `backend/media_gateway.py` | 해제 실패한 미디어 세션 재시도/소유자 접근 차단 |
| `backend/monitor.py`, `.env.example` | 수신 시각 명시, 검증된 촬영 시계 없을 때 보수적 ReID |
| `backend/test_media.py` | RTSP 병합 응답/RTP 순서, 세션 해제 재시도, upstream 경로 검증 |
| `src/WebRTCLive.jsx` | 연결 취소·경쟁 방지·시간 제한·분석 신선도 |
| `src/MonitorPlayer.jsx` | AI 없는 영상 pause, FPS 중복 제거 |
| `src/MultiCameraMonitor.jsx` | 영상/AI 상태와 최근 수신 표시 |
| `vite.config.js` | 녹화·가중치·비밀파일·가상환경 감시 제외 |
| `tools/test_media_integration.py` | 실제 네이티브 송출/브라우저 검증 강화, 포트 사전 검사, 자식 프로세스 정리 |
| `docs/media-integration-result.json`, `docs/media-no-model-result.json` | 실제 실행한 테스트 결과 |
| `docs/benchmark-reid.json` | 실제 OSNet 두 모델 추론 측정 갱신 |
| `docs/CODEX-PROGRESS.md` | 중단/재개 기록 |
| `docs/PHONE-LIVE-STREAM-SETUP.md`, `docs/AWS-LIVE-STREAM-DEPLOY.md`, 이 문서 | 설정·운영·검증 설명 |
| `README.md`, `docs/LOCAL-RUN.md`, `docs/MULTICAMERA.md` | 최신 문서 연결 및 과거 기록 구분 |

이 변경들은 작업 트리에 보존했다. 임의 커밋/원격 push/AWS 리소스 생성은 하지 않았다.

## 4. 테스트 결과

| 검증 | 결과와 한계 |
|---|---|
| Python unittest | 81개 중 77 성공, 4 skip. 실제 best.pt+test.mp4 1개, PostgreSQL 3개 미준비 |
| Node 테스트 | 5/5 성공: 프레임 분리, 텍스트 위치, RTP 시각/세대/버퍼 제한 |
| npm run build | 성공, 1,586 modules |
| pip check | 의존성 충돌 없음 |
| MediaMTX 설정 | v1.21.3 네이티브 `--validate-conf` 성공 |
| Compose 구성 | 공식 standalone v5.7.0 / SHA256 검증 후 병합 `config --quiet` 성공. 임시 비밀값으로 스키마/보간 검증 |
| Docker 이미지/실행 | 건너뜀: Docker 엔진 없음 |
| 3채널 RTMPS | FFmpeg H.264 640×360 15FPS, 각기 다른 합성 색상 영상, 로컬 CA TLSv1.3 검증 성공 |
| 실제 WebRTC 브라우저 | Chromium 3개 영상, 같은 RTP 프레임 텍스트, pause/fullscreen 성공 |
| 독립 장애 | CAM-01 중단→offline→새 ready_time으로 복구, CAM-02 재생 지속 확인 |
| 인증 | 틀린 암호, 다른 CAM 경로, 익명 직접/프록시 WHEP 거부; 로그아웃 후 MediaMTX 실제 viewer 0개 확인 |
| 이벤트/DVR | 합성 detector 결과 이벤트 저장 및 프레임 조회 성공. 실제 보호구 정확도 검증 아님 |
| 모델 없는 실앱 | fixture 없이 main:app 실행, YOLO missing / OSNet ready, 세 영상 독립 재생·제어·인증 성공 |
| 기존 UI 회귀 | 바이너리 3채널, 개별 pause, 전체화면, 개별/전체 제어, 이벤트→CAM-02 DVR, 반응형 성공 |
| 기본 로컬 앱 | 실제 로그인 데모 버튼, 3분할 가로 배치, 전체화면, API HTTP200, JS 예외 없음 |
| OSNet | 두 실제 ONNX 모델에서 정규화 512차원 특징 추론 성공. 합성 RGB crop 사용, 실제 동일인 정확도 미검증 |

실패 이력: RTSP 파싱 오류를 수정했다. 초기 Vite 연결 지연을 runtime watch 제외 후 재검증했다.
모델 없는 시험에서 잘못된 송출 프로세스를 2초 만에 종료 판정하던 테스트가 간헐 실패하여
상태 기반 최대 대기로 변경했고 최종 통과했다. 로컬 브라우저 즉석 점검의 PowerShell 한국어 전달 오류도
선택자 수정 후 정상 완료했다. 성공 결과 JSON에는 최종 통과 실행만 반영했다.

## 5. FPS·지연 측정

`media-integration-result.json`의 5초 동시 비교 기준:

| 항목 | 측정 |
|---|---|
| WebRTC 각 채널 디코딩 FPS | 약 15.0 |
| 기존 CAM-01 바이너리 도착 FPS | 약 4.8 |
| 합성 검출 파이프라인 분석 FPS | 약 4.7~4.8 |
| WebRTC 채널당 수신량 | 약 157 KB/s |
| CAM-01 바이너리 수신량 | 약 91 KB/s |
| WebRTC 평균 지터 버퍼 | 약 131ms |
| OSNet x0.25 / x1.0 crop 추론 중앙값 | 약 12.0ms / 475.3ms (CPU, 각 30회) |

WebRTC는 분석 속도와 독립적으로 원본 15FPS를 전달했다. 이 시험에서 전체 수신량은 바이너리보다 컸으므로
대역폭 절감으로 설명하지 않는다. 화면 FPS의 짧은 샘플 중 CAM-02는 11.6FPS도 관측되었다.
지터 버퍼/서버 frame_age는 촬영→표시 전체 지연이 아니다. 실제 YOLO FPS, 공중망 지연 및 실제 인물 ReID 정확도는 미측정이다.

## 6. 현재 로컬 실행 상태

- 프론트엔드: http://127.0.0.1:5173 — 정상, 프로세스 유지.
- 백엔드: http://127.0.0.1:8002 — 정상, `/health` HTTP200.
- 로그인: **로컬 데모로 대시보드 보기**. 기존 계정 PostgreSQL 인증은 별도 미검증.
- YOLO: 실제 best.pt 없음, 로드/실제 추론 미검증.
- OSNet: 실제 모델 로드 성공.
- DB: 격리된 로컬 SQLite 연결 성공, 운영 PostgreSQL 미설정.
- 카메라: CAM-01 기존 직접 입력 설정 보존, 감지 대기; CAM-02/03 미설정. 현재 실제 폰 영상을 확인한 상태가 아니다.
- 기본 서버 `MEDIA_ENABLED=false`: 별도 합성 통합 테스트의 MediaMTX/FFmpeg/브라우저 프로세스는 종료했다.
- 스크린샷/로컬 결과: `.local-run/verification/resumed-dashboard.png`, `resume-result.json` (Git 제외).

```powershell
cd C:\vscode\AI-Construction-Safety-Monitoring
.\.venv\Scripts\python.exe tools/run_local.py status
# 다음 실행 시
.\.venv\Scripts\python.exe tools/run_local.py start --mode demo
# 이번 도구가 실행한 서버만 종료, 데이터 보존
.\.venv\Scripts\python.exe tools/run_local.py stop
```

직접 카메라 주소는 Git 제외 `.env.local-run`의 `CAMERA_01_SOURCE`~`CAMERA_03_SOURCE`에 넣는다.
한 채널만 설정해도 된다. 파일 변경 시 로컬 도구로 stop/start한다. Push 모드는 별도 AWS 가이드를 따른다.

## 7. AWS 준비 상태

MediaMTX/인증/AI/WebRTC 통합 코드, Compose 파일, 역할 분리, TLS 마운트/공개 포트 설계와 문서 준비.
실제 Docker 이미지 빌드, 공인 DNS/TLS, HTTPS 웹 프록시, AWS SG 및 ICE 검증은 미완료다.
현재 설정 파일만으로 공개 서버가 생기지는 않는다. [배포 가이드](AWS-LIVE-STREAM-DEPLOY.md).

## 8. Larix 설정

실제 송출 DNS를 준비한 후 `tools/issue_stream_credentials.py --host 실제DNS`로 생성한다.
각 폰은 개인 JSON의 자기 CAM `connection_url` 전체를 Connections에 입력한다. 기본 H.264/720p/15FPS,
B-frame 없음, 별도 Login/Password는 비움. URL 쿼리에 각 CAM 비밀번호가 들어 있으므로 공유 로그에 출력하지 않는다.
[Android/iPhone 전체 단계](PHONE-LIVE-STREAM-SETUP.md). 현재 발급 가능한 실제 AWS 주소는 아직 없다.

## 9. 반드시 남아 있는 검증/개발

실제 스마트폰 한 대부터 세 대로 확대하고 서로 다른 Wi-Fi/LTE/5G, 네트워크 전환, 앱 잠금/발열,
24시간 송출을 확인해야 한다. FFmpeg 로컬 CA 시험은 이 검증을 대체하지 않는다.
best.pt 제공 후 실제 클래스/추론/이벤트 검증, 실제 PostgreSQL 계정 인증,
공통 촬영 시계와 Push 간 자동 ReID 연결, 인물 정확도 평가, TURN 필요망 지원이 남았다.
송신 시계를 검증하지 않은 Push 입력은 Global ID를 채널 간 동일인으로 자동 확정하지 않는다.

## 10. 다음 재개 지점

[CODEX-PROGRESS.md](CODEX-PROGRESS.md)를 읽고 현재 git diff/프로세스/결과 JSON을 먼저 확인한다.
외부 환경이 준비되면 Docker 빌드 → 실제 best.pt → 공개 DNS/TLS/ICE → Larix 1대 → 3대 순으로 진행한다.
이번에 통과한 순수 로컬 테스트를 이유 없이 처음부터 다시 구현하지 않는다.
