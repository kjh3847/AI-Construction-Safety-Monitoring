# AI 건설현장 안전 모니터링 개선 결과

작업 기준은 로컬 저장소 `572ef4b`입니다. 시작 시 작업 트리는 깨끗했습니다.
변경은 로컬 작업 트리에 있으며 GitHub push, 운영 서버 변경, AWS 유료 리소스 생성은 수행하지 않았습니다.

## 1. 기존 코드에서 확인한 문제와 원인

- main.py에 실제 입력 대신 고정된 사설 주소 3개가 들어 있었고, 모델도 3번 로딩했습니다.
- Monitor는 `use_camera_env=False`로 전달된 HTTP URL을 시험 파일로 분류해 로컬 파일 해시를 시도할 수 있었습니다.
- 카메라가 끊기면 감지 작업이 종료되고 자동 복구되지 않았습니다. 기존 최신 프레임 수신 구조는 복구 기능이 없었습니다.
- 모델 3개를 공통 잠금으로 직렬 실행하면서 추론 순서의 공정성도 보장하지 않았습니다.
- `result.plot()`이 박스를 JPEG에 합성하고, 라이브 화면이 저장 파일을 HTTP/JSON/Base64로 다시 읽었습니다.
- 프론트는 선택된 플레이어 하나만 마운트해 동시 관제가 불가능했습니다.
- 기존 PersonTracker는 카메라 내부 공간 추적만 수행했습니다. BoT-SORT 사용만으로 카메라 간 ReID가 구현되지는 않았습니다.
- 기존 source 테스트는 2채널·`main.model`/`main.VIDEO_PATH`를 전제로 하여 실제 3채널 코드와 맞지 않았습니다.

## 2. 수정 및 추가 파일

기존 파일:

- 입력·분석·이벤트: `backend/main.py`, `backend/monitor.py`, `backend/live_capture.py`, `backend/person_tracker.py`, `backend/event_recorder.py`, `backend/database.py`
- 화면: `src/main.jsx`, `src/MonitorPlayer.jsx`, `src/EventPanel.jsx`, `src/data.js`, `src/dashboard.css`, `vite.config.js`
- 기존 검증: `backend/test_monitor.py`, `backend/test_recording.py`, `backend/test_sources.py`, `backend/video_test_support.py`
- 설정·안내: `.env.example`, `.gitignore`, `README.md`, `CCTV.md`, `IPHONE-CAMERA.md`

추가 파일:

- 입력·추론·저장·ReID: `backend/camera_config.py`, `backend/inference.py`, `backend/frame_store.py`, `backend/reid.py`, `backend/requirements-runtime.txt`
- 화면·전송: `src/MultiCameraMonitor.jsx`, `src/frameProtocol.js`, `src/frameProtocol.test.js`
- 테스트: `backend/test_botsort.py`, `backend/test_live_api.py`, `backend/test_monitor_worker.py`, `backend/test_multicamera.py`, `backend/test_reid.py`
- 배포: `.dockerignore`, `compose.monitor.yaml`, `deploy/Dockerfile.monitor`, `deploy/Dockerfile.web`, `deploy/nginx.monitor.conf`
- 도구: `tools/check_baseline.py`, `tools/test_browser.py`, `tools/test_mjpeg.py`, `tools/benchmark_transport.py`, `tools/benchmark_reid.py`, `tools/prepare_osnet.py`, `tools/export_osnet.py`
- 문서·측정: `docs/MULTICAMERA.md`, 이 보고서, `docs/benchmark-synthetic.json`, `docs/benchmark-reid.json`, `docs/osnet-provenance.json`

공식 OSNet checkpoint·소스·라이선스·검증된 ONNX는 로컬 `models/`에 준비했으며 Git에서 제외했습니다.
실제 학습 `best.pt`는 제공되지 않아 대체하지 않았습니다. 기존 계정 코드와 실제 데이터 파일은 변경하지 않았습니다.

## 3. 구현한 기능과 남은 기능

구현:

- 3분할 반응형 화면, 개별 일시정지/확대/전체화면/감지 제어, 통합 시작·중단, 현재 인원·미착용·연결 상태 표시.
- 3개 독립 Capture, 최신 프레임 우선, 5초 기본에서 최대 60초 지수 백오프, 동일 포트/다른 IP 허용, 중복 endpoint 경고.
- 모델 가중치 하나와 FIFO 추론 순서, 카메라별 BoT-SORT/공간 추적/이벤트 연속성. BoT-SORT는 Person만 추적합니다.
- 바이너리 WebSocket, 프레임/메타데이터 결합, 브라우저의 최신 패킷 우선 디코딩, 박스 없는 원본 JPEG와 텍스트 표시.
- 카메라별 수신 FPS·분석 FPS·추론/대기/JPEG/디스크 시간·서버 수신 이후 프레임 나이, 브라우저 표시 FPS·수신량, 서버 CPU/RSS/free disk.
- 비동기 녹화, 프레임 디스크 인덱스, 기존 JPEG/JSON의 추가 마이그레이션, 용량 상한·1GiB 여유 공간 검사.
- 실제 OSNet ONNX 특징 추출, Global ID, 이동 시간/유사도/동시 등장/모호성/품질 제한, 최근 갤러리 복원, 수동 수정과 감사 기록.
- 이벤트의 stable camera ID·Local ID·Global ID·tracklet·유사도·상태 저장, 보수적인 중복 새 감지 알림 생략. 10분 경고의 로컬 증거 연속성 유지.
- 인증된 영상·이벤트·추적 API, WS origin/세션 확인, 운영 구성 및 백업·용량·네트워크 안내.

남음:

- 실제 스마트폰 앱 3대/RTSP/USB, 현장 이동 영상의 ReID 정확도·오인식률, 실제 best.pt 클래스/성능/정확도 검증.
- AWS 배포, Docker 실제 이미지 빌드, 실제 도메인의 HTTPS/WSS·쿠키·CORS·RDS, GPU 및 24시간 부하/복구 시험.
- 전용 현장 push relay, WebRTC, 오디오/원본 FPS MP4, 장기 JPEG 보관을 구간 영상으로 바꾸는 작업.

## 4. 카메라 설정 및 실행

`.env.example`을 바탕으로 `CAMERA_01_SOURCE`~`CAMERA_03_SOURCE`에 앱이 제공하는 실제 영상 endpoint를 넣습니다.
`MODEL_PATH`는 기존 best.pt, `MONITOR_STORAGE_DIR`는 영구 녹화 경로입니다.
`DATABASE_URL`, `PUBLIC_APP_URL`, 쿠키·계정 설정도 기존 절차에 따라 준비합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-runtime.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8002 --workers 1 --env-file .env
# 별도 터미널에서
$env:ACCOUNTS_API_URL='http://127.0.0.1:8002'
npm.cmd run dev
```

ReID 모델은 `REID_MODEL_PATH=models/osnet_x0_25.onnx`로 지정할 수 있습니다.
실제 카메라 배치에서 측정한 방향별 최소/최대 이동 시간을 `REID_TRANSITIONS`에 설정해야 카메라 간 자동 연결이 활성화됩니다.
Docker에서는 경로를 `/models/osnet_x0_25.onnx`로 지정합니다.
전체 설치, 초기 계정, VPN, 용량 정책은 [운영 안내](MULTICAMERA.md)에 정리했습니다.

## 5. Global Person ID와 ReID 원리

YOLO 검출 → 카메라 내부 BoT-SORT/PersonTracker → 인물 crop의 OSNet 512차원 정규화 벡터 → 최근 후보와 cosine 비교 순서입니다.
기본 유사도 0.88, 후보 간 차이 0.08, 설정된 방향별 이동 시간과 최소 2초 비동시 등장 조건을 모두 통과해야 연결합니다.
카메라 관계를 모르면 연결하지 않습니다. 흐림/작은 crop/낮은 신뢰도/가림은 특징 매칭에서 제외합니다.
ID는 익명 추정값이고 실제 신원이 아니며 `unconfirmed`/`estimated`/`manual` 상태를 표시합니다.
관리자 수정은 선택 tracklet의 이벤트 연결만 고치고 기존 프레임의 당시 분석 정보는 보존합니다.
카메라 이동·단절 시간을 10분 미착용 지속 시간에 더하지 않습니다.

## 6. 실제 실행한 검사와 결과

| 검사 | 결과 | 검증 범위 |
|---|---|---|
| 수정 전 최초 테스트 | 26개 실행, 오류 10개 | 패키지 부재. 원본 로그는 로컬 baseline-tests.log |
| 의존성 설치 후 깨끗한 HEAD 별도 실행 | 49개: 통과 44, 오류 2, 건너뜀 3 | 오류는 best.pt 부재. source 테스트의 오래된 전제도 코드에서 확인 |
| 최종 backend unittest | 65개: 통과 61, 건너뜀 4 | 합성 탐지·임시 DB·실제 BoT-SORT·실제 decoder/DVR·기존 회귀 |
| 건너뛴 검사 | best.pt/시험 영상 1개, 별도 PostgreSQL 테스트 DB 3개 | 성공으로 간주하지 않음 |
| Node 전송·라벨 검사 | 2개 통과 | 다른 카메라 패킷 차단, 텍스트 좌표·겹침·경계 |
| Chromium UI | 통과 | 3개 Canvas, 개별 정지 중 다른 화면 갱신, 전체화면, 제어 대상, CAM-02 이벤트 이동, 반응형, JS 오류 없음 |
| OpenCV/FFmpeg MJPEG | 통과 | 동일 포트/서로 다른 loopback IP의 3개 실제 HTTP decoder, 1번 실패·복구 두 번, 2·3번 유지, 종료 리소스 해제 |
| OSNet x0.25 및 x1.0 내보내기 | 통과 | 실제 공식 MSMT17 가중치의 trunk 검사, PyTorch/ONNX 정규화 출력 일치, 실제 512차원 벡터 |
| npm run build | 통과 | Vite production build |
| compileall / pip check / git diff --check | 통과 | 구문, 패키지 호환성, whitespace |

브라우저의 API/영상은 명시적 합성 fixture입니다. MJPEG 검사는 로컬 HTTP 모의 폰입니다.
Worker 검사는 합성 검출 결과를 실제 BoT-SORT·이벤트·녹화에 연결했으며 실제 YOLO 정확도를 측정한 것이 아닙니다.
ReID 매칭 정책은 합성 벡터로 1→2→3 이동, 유사 복장 후보 보류, 동시 등장 차단, 모델 교체,
재시작/재연결, 수동 분리, 알림 중복 및 미관찰 시간 제외를 검증했습니다.

## 7. 성능 비교 수치와 환경

환경: Windows 11 build 26200, Intel Family 6 Model 151, 논리 CPU 12개, Python 3.14.5,
OpenCV 5.0.0, PyTorch 2.15.0, Ultralytics 8.4.152, ONNX Runtime 1.31.1, Node 26.13.0.

같은 합성 JPEG와 메타데이터를 사용한 마이크로벤치마크입니다.

| 항목 | 기존 | 변경 후 |
|---|---:|---:|
| JPEG 자체 | 155,064 bytes | 155,064 bytes |
| 패킷 크기 | JSON/Base64 207,760 bytes | binary 155,924 bytes (약 24.9% 감소) |
| 패킷 구성 중앙값 100회 | 0.7698ms | 0.0124ms |
| 1,000프레임 재시작 Python heap peak | 7,347,971 bytes | 4,583 bytes |
| 1,000프레임 정확한 프레임 조회 중앙값 | 0.8095ms | 2.0136ms |

새 인덱스는 작은 자료에서 디스크 조회·메타데이터 재읽기 때문에 조회 시간이 늘었습니다.
기간이 긴 자료에서 메타데이터 전체를 Python 메모리에 올리지 않는 목적의 선택입니다.
heap 수치는 tracemalloc 결과로 SQLite native cache나 전체 프로세스 RSS를 포함하지 않습니다.
원시 결과는 [benchmark-synthetic.json](benchmark-synthetic.json)입니다.

실제 학습 OSNet 모델의 합성 crop 1개에 대한 CPU 단일 스레드, 3회 워밍업 후 30회 측정:

| 항목 | OSNet x0.25 | OSNet x1.0 |
|---|---:|---:|
| ONNX 크기 | 891,549 bytes | 8,729,490 bytes |
| crop 추출 중앙값 | 12.625ms | 576.261ms |
| CPU 시간/crop | 13.021ms | 555.208ms |
| 측정 프로세스 RSS | 85,794,816 bytes | 107,233,280 bytes |

이 로컬 환경에서는 x0.25를 기본 후보로 선택했습니다. RSS는 각 모델만의 메모리량이 아니며
전체 모델/라이브 운영 성능이나 현장 정확도 우위를 입증하지 않습니다.
출처·해시는 [osnet-provenance.json](osnet-provenance.json), 결과는 [benchmark-reid.json](benchmark-reid.json)에 있습니다.

실제 카메라별 표시 FPS·AI FPS·전체 처리 시간·표시 지연·시스템 CPU/GPU·모델 메모리·실제 회선 전송량·하루 녹화 증가량의
전후 비교는 best.pt와 현장 입력이 없어 측정하지 못했습니다. 관련 실측 지표는 실행 중 UI/API에 제공하도록 구현했습니다.
특정 FPS를 보장하지 않습니다. 30일 용량 산식과 2FPS/5FPS 예시는 운영 안내에 있습니다.

## 8. AWS 실행에 필요한 단계

1. 현장 gateway에서 outbound VPN 또는 현장 라우터의 Site-to-Site VPN을 구성하고 EC2 컨테이너에서 3개 실제 스트림을 검증합니다.
2. 실제 best.pt·ReID 모델·기존 DB/영상의 백업을 준비하고 영구 volume으로 안전하게 이전합니다.
3. 운영 origin/secure cookie/RDS TLS/비밀 주입을 설정하고 `compose.monitor.yaml`을 실제 빌드·기동합니다.
4. 기존 Nginx/ALB로 HTTPS/WSS를 제공하고 backend·DB·카메라·녹화 파일의 직접 외부 접근을 차단합니다.
5. 로그인/로그아웃/비밀번호 변경, WS 세션 만료, CORS/Origin, 카메라 단절·서버 재시작·녹화 복구를 실제 환경에서 검증합니다.
6. CPU/GPU 자원과 분석/녹화 FPS를 실측으로 선정하고 디스크·inode·로그·카메라·지연 경보와 백업 복구 훈련을 수행합니다.

Docker가 이 환경에 없어 이미지 빌드/Compose 실행은 수행하지 않았습니다.
nginx/TLS와 AWS 네트워크 구성은 현장 검증 전의 준비 자료입니다.

## 9. 남은 위험과 개선 과제

- 실제 유사 작업복·가림·카메라 시점의 오인식률을 측정하지 않았습니다. 기본 매칭 임계값은 현장 평가로 보정해야 합니다.
- 영상 표시가 분석 완료 FPS를 따릅니다. 고해상도/많은 인물에서는 CPU 추론·ReID가 병목이 될 수 있습니다.
- 서버 수신 이전의 폰 인코딩/네트워크 지연은 timestamp 계약이 없어 분리 측정하지 못합니다.
- 녹화 큐 포화나 디스크 부족 시 저장 누락을 표시합니다. 이벤트 DB 이력은 남아도 일부 증거 프레임이 없을 수 있습니다.
- 30일 JPEG/JSON은 수천만 파일이 될 수 있습니다. 디스크 인덱스가 메모리 부담을 줄여도 파일 수와 저장 비용은 남습니다.
- FFmpeg open/read timeout으로 네트워크 작업을 제한했지만 실제 RTSP/USB 드라이버의 종료 동작과 장기 안정성은 별도 검증이 필요합니다.
- 기존 박스가 영구 합성된 JPEG는 원본 없이 복구할 수 없습니다. 새 프레임부터 텍스트 메타데이터 방식입니다.
- 익명 Global ID도 외형 기반 추정값입니다. 수동 수정 시 후속 tracklet 전체를 임의 변경하지 않으므로 관련 기록을 함께 검토해야 합니다.
- ONNX export는 현재 호환되는 legacy TorchScript 경로이며 향후 PyTorch 업그레이드 시 재검증해야 합니다.
