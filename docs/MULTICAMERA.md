# 3대 동시 관제 실행과 운영 (2026-11-10)

스마트폰 Push 입력과 WebRTC 추가 사항은 [AWS/MediaMTX 구성](AWS-LIVE-STREAM-DEPLOY.md),
[Larix 설정](PHONE-LIVE-STREAM-SETUP.md), [최신 검증 결과](LIVE-STREAM-REPORT.md)를 먼저 확인한다.
아래 직접 카메라/바이너리 전송 기능은 보존된다. Push 간 자동 ReID 연결은 공통 촬영 시계 검증 전까지 비활성이다.

## 변경 범위와 데이터 흐름

기존 FastAPI·React·PostgreSQL 계정·SQLite 이벤트·JPEG DVR 구조를 확장했습니다.
계정 API와 로그인, 강제 비밀번호 변경, 계정 관리, 이벤트 확인, CSV, 로컬 파일 미리보기,
과거 영상 시간 탐색 및 10분 지속 미착용 경고를 유지합니다. 운영 서버나 GitHub 원격에는 적용하지 않았습니다.

```
카메라별 Capture → 최신 프레임 1개 → FIFO 공유 YOLO predict
  → 카메라별 BoT-SORT + PersonTracker → 보호구 증거 연결 → GlobalTracker
  → 원본 JPEG + 같은 프레임 메타데이터 → 인증된 binary WebSocket → Canvas 텍스트
  → 별도 녹화 스레드 → JPEG/JSON + SQLite 프레임 인덱스 → 기존 DVR API
```

기존 문제는 하드코딩된 주소, URL의 시험 파일 오분류, 재연결 부재, 모델 3개의 중복 로딩,
불공정한 공통 잠금, `result.plot()`으로 박스가 영구 저장되는 구조,
라이브 화면의 디스크 읽기·Base64·200ms HTTP 폴링, 선택 카메라 하나만 렌더링하는 구조였습니다.
3대가 같은 모델 가중치 하나를 FIFO 순서로 사용하고 추적·재연결·녹화 상태는 각각 분리합니다.
Ultralytics의 공유 모델은 잠금이 필요하므로 추론 자체는 직렬입니다.
BoT-SORT의 내부 전역 ID 카운터도 카메라별로 격리해 다른 카메라 재연결의 영향을 막았습니다.

## 로컬 실행

계정 DB 없이 화면을 먼저 확인하려면 [Windows 로컬 데모 실행 안내](LOCAL-RUN.md)를 사용합니다.
아래는 실제 PostgreSQL 계정을 사용하는 정상 모드의 실행 절차입니다.

Python 3.12 이상, Node 22.12 이상, 기존 계정 PostgreSQL과 실제 학습 `best.pt`가 필요합니다.
Git 추적 파일에는 학습 가중치, 카메라 영상, ReID 가중치가 없습니다. 임의 모델로 대체하지 않습니다.
이번 로컬 검증용 공식 OSNet 가중치와 내보낸 ONNX는 Git 제외된 `models/`에 준비했습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-runtime.txt
npm.cmd ci
Copy-Item .env.example .env
```

`.env`에 기존 계정 DB·발신 이메일 설정과 실제 스트림 주소를 넣습니다.
DB가 처음이면 `backend/bootstrap_system.py`로 기존 절차에 따라 시스템 계정을 생성합니다.
관리자 계정 관리와 이메일 발급 절차는 [ACCOUNTS.md](../ACCOUNTS.md)를 따릅니다.

```dotenv
CAMERA_01_SOURCE=<첫 번째 실제 영상 스트림>
CAMERA_02_SOURCE=<두 번째 실제 영상 스트림>
CAMERA_03_SOURCE=<세 번째 실제 영상 스트림>
CAMERA_01_NAME=CAM-01
CAMERA_02_NAME=CAM-02
CAMERA_03_NAME=CAM-03
CAMERA_RECONNECT_ENABLED=true
CAMERA_RECONNECT_INTERVAL=5
MODEL_PATH=<기존 best.pt 절대 경로>
MONITOR_STORAGE_DIR=<녹화 폴더 절대 경로>
PUBLIC_APP_URL=http://localhost:5173
COOKIE_SECURE=false
```

`0`은 USB, 로컬 경로는 시험 파일, HTTP(S)·RTSP(S)는 네트워크 입력으로 판별합니다.
`CAMERA_SOURCE`는 호환 목적으로 CAM-01에만 적용됩니다.
미설정 카메라는 대기 상태이며, 기존 `backend/test.mp4` 등이 실제 존재할 때만 해당 시험 파일을 사용합니다.
설정 파일은 Uvicorn의 `--env-file`로 읽습니다. 별도 dotenv 의존성을 피하려면 환경변수를 직접 설정합니다.
`--env-file`에 필요한 `python-dotenv`는 runtime 의존성에 포함했습니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8002 --workers 1 --env-file .env
# 다른 터미널: 기존 클라우드 계정 API 대신 동일 백엔드를 사용하려면 설정
$env:ACCOUNTS_API_URL='http://127.0.0.1:8002'
npm.cmd run dev
```

`http://localhost:5173`에 로그인하고 전체 또는 개별 감지·녹화 시작을 누릅니다.
개별 일시정지/확대/전체화면은 화면만 변경합니다. 이벤트의 “해당 시점 영상 보기”는 그 카메라만 과거 모드로 바꿉니다.
합계 인원은 카메라별 현재 검출의 합계이며 고유 작업자 수가 아닙니다.
일시정지/과거 재생/수신 중단 화면은 현재 합계에서 제외합니다.

앱의 웹 관리 화면과 영상 endpoint를 구분해야 합니다. `/video`나 RTSP 경로는 앱마다 다르므로
실제 주소를 앱 설명과 VLC/ffprobe로 확인합니다. 서로 다른 IP의 동일 포트는 정상이며,
같은 endpoint를 두 번 입력하면 주소를 노출하지 않고 중복 경고를 표시합니다.
HTTP MJPEG는 로컬 FFmpeg 실수신으로 검증했지만 실제 스마트폰 앱·RTSP·USB는 현장 확인이 필요합니다.

## ReID 설정과 판단 범위

OSNet은 모델 계열이고 Torchreid는 그 모델을 제공하는 PyTorch 구현입니다.
선택한 경로는 **Torchreid의 학습된 OSNet x0.25 → ONNX → ONNX Runtime CPU 추론**입니다.
기존 PyTorch 실행 계층과 별도로 가벼운 특징 추출만 배포할 수 있습니다.
x1.0도 내보내어 같은 합성 crop에서 CPU 추론 시간을 비교했습니다.
Windows 11/Python 3.14.5/ORT 1.31.1, CPU 단일 추론 스레드에서 중앙값은
x0.25 **12.625ms**, x1.0 **576.261ms**였습니다(각 30회, 워밍업 후 측정).
내보낸 파일은 각각 891,549/8,729,490바이트입니다. 현장 정확도 비교는 평가 영상 부재로 수행하지 못했습니다.
이 수치는 해당 로컬 환경의 특징 추출 시간이며 전체 YOLO 파이프라인 FPS가 아닙니다.
Torchreid 전체 런타임은 데이터셋·학습 관련 의존성이 늘어 운영 이미지에 넣지 않았습니다.
Torchreid 코드는 MIT이며 학습 데이터/배포 가중치의 별도 사용 조건은 준비한 가중치 출처에서 확인해야 합니다.
기존 Ultralytics 라이선스는 계속 적용됩니다.

신뢰할 수 있는 upstream Torchreid checkout과 해당 모델의 학습 checkpoint, `onnx`를 별도 내보내기 환경에 준비합니다.
무작위 가중치 또는 ImageNet만 학습한 모델을 사람 ReID로 표시하지 않습니다.

```powershell
python -m pip install onnx
# 연구자 공식 MSMT17 checkpoint와 MIT 소스를 models/에 준비
python tools/prepare_osnet.py
python tools/export_osnet.py --source models/upstream_osnet.py --weights models/osnet_x0_25_msmt17.pth --output models/osnet_x0_25.onnx
# Torchreid 전체 패키지가 설치된 별도 환경에서의 대안
python tools/export_osnet.py --model osnet_x0_25 --weights <학습된 checkpoint> --output models/osnet_x0_25.onnx
```

이 스크립트는 trunk 가중치의 완전성과 ONNX/PyTorch의 정규화 벡터 일치를 검사합니다.
공식 MSMT17 학습 checkpoint로 두 모델을 내보냈고, 두 종류의 입력에서 정규화 원소 오차 1e-4 이하와
cosine 0.99999 이상 검사를 통과했습니다. 이 수치 검사는 실제 동일인 매칭 정확도를 뜻하지 않습니다.
다운로드 출처/해시는 [OSNet 출처 기록](osnet-provenance.json), 측정값은 [ReID 측정](benchmark-reid.json)에 있습니다.
검증된 ONNX 파일이 이미 있다면 RGB/ImageNet 정규화, NCHW 1×3×256×128 입력과 특징 벡터 출력 계약을 확인합니다.

```dotenv
REID_MODEL_PATH=<검증한 ONNX 절대 경로>
REID_THRESHOLD=0.88
REID_THREADS=1
# 실제 카메라 배치에서 측정한 방향별 최소/최대 이동 시간(초)만 입력
REID_TRANSITIONS={"CAM-01>CAM-02":[3,30],"CAM-02>CAM-03":[4,45]}
```

위 이동 시간은 설정 형식 예시이며 실제 배치에 그대로 적용하면 안 됩니다.
연결 관계 기본값 `{}`에서는 카메라 간 자동 연결이 비활성입니다.
모델 미설정/실패 상태도 화면에 표시하며 얼굴 인식이나 신원 확인은 수행하지 않습니다.

- Local ID는 카메라·실행 세션 안에서 유지합니다. Global ID는 `P`와 16자리 임의 토큰인 익명 추정 ID입니다.
- 특징 벡터의 cosine 유사도, 방향별 이동 시간, 최근 2초 동시 등장 금지, 후보 간 점수 차이 0.08을 함께 사용합니다.
- 유사 후보가 여럿이거나 기준 미달, 흐림, 작은 crop, 낮은 검출 신뢰도, 30% 이상 가림은 매칭하지 않습니다.
- 기본 후보 창은 5분입니다. 재시작 시 DB의 최근 tracklet과 같은 모델 fingerprint의 벡터를 복원합니다.
- `estimated`는 동일인 추정, `unconfirmed`는 미확정, `manual`은 관리자 수정입니다. 점수는 검증된 확률이 아닙니다.
- `/api/people?global_id=...`로 이력을 조회합니다. 화면의 추적 기록에서 ID 연결/분리 및 사유 입력이 가능합니다.
- 수정은 선택 tracklet에 연결된 DB 이벤트만 고치고 감사 기록을 남깁니다. 원본 프레임 메타데이터는 당시 판단을 보존합니다.
- 파일 재생은 파일/모델 해시로 같은 증거의 ID와 중복 방지를 유지합니다. 카메라 재연결은 새 local 세션을 만듭니다.
- 카메라 이동 후 60초 이내 동일한 위반 종류가 유사도 0.92 이상으로 연결된 경우, 이벤트는 보존하고 “새 감지” 알림만 생략합니다.
- 10분 지속 경고는 카메라별로 새로 관찰한 연속 증거에만 적용합니다. 이동/통신 공백을 미착용 지속 시간에 더하지 않습니다.

## 텍스트와 전송·저장 정책

`result.plot()`을 제거하고 원본 JPEG와 분석 결과를 함께 전송합니다.
Canvas는 사람 가까이에 ID와 명시적 보호구 미착용 증거를 텍스트로 그립니다. 검출 박스 좌표는 내부 분석에 사용합니다.
보호구가 안 보였다는 이유만으로 정상/미착용을 확정하지 않고 “미착용 증거 없음”으로 표시합니다.
과거 JPEG에 박스가 이미 합성되어 있고 원본이 없으면 제거할 수 없습니다.

WebSocket 패킷은 `4바이트 big-endian JSON 길이 + UTF-8 metadata + JPEG bytes`입니다.
카메라 ID·recording ID·frame ID가 JPEG와 함께 도착하므로 최신 메타데이터를 과거 영상에 얹지 않습니다.
브라우저 디코딩 대기열도 최신 패킷 하나만 유지합니다. 과거 탐색은 기존 JSON/Base64 API를 유지합니다.
MJPEG는 메타데이터 동기화가 어렵고, WebRTC는 별도 미디어 서버/시그널링이 필요해 이번 구조에서는 바이너리 WebSocket을 택했습니다.

기본 `ANALYSIS_FPS=5`, `RECORDING_FPS=2`는 목표 상한이며 보장 FPS가 아닙니다.
실시간 표시는 분석이 끝난 프레임에 맞춥니다. 분석하지 않은 원본을 더 높은 FPS로 보여주면서
오래된 분석 결과를 현재 결과처럼 표시하는 방식은 채택하지 않았습니다.
`CAPTURE_MAX_WIDTH`, `INFERENCE_SIZE`, `INFERENCE_DEVICE`를 현장 측정에 맞춰 조절합니다.
기본 CPU 실행이며 GPU는 호환 PyTorch/CUDA 이미지와 컨테이너 GPU 노출을 별도 검증해야 합니다.

녹화는 원본 FPS MP4/음성이 아닌 JPEG 샘플+JSON입니다. 이벤트 발생 프레임도 별도 저장합니다.
녹화 대기열은 카메라별 32개로 제한되며 디스크 지연 시 누락 수와 오류를 표시합니다.
디스크가 1GiB 미만이면 새 녹화를 거절하되 라이브 분석을 계속합니다.
`RECORDING_MAX_BYTES_PER_CAMERA`가 0이면 기간 기준, 양수이면 용량 초과 시 가장 오래된 프레임부터 정리합니다.
스냅샷은 기간 기준, DB 이벤트 이력은 삭제하지 않습니다. 실제 보관 기간은 화면의 저장 범위로 확인합니다.

프레임 인덱스는 각 `frames/index.sqlite3`에 있으며 JSON 전체를 메모리에 올리지 않습니다.
기존 JPEG/JSON은 첫 실행 때 한 번 인덱스에 추가합니다. 파일을 나중에 수동 복구한 경우
서비스 중단·전체 백업 후 해당 인덱스 파일을 별도 이름으로 이동하면 다음 실행에서 JSON을 다시 가져옵니다.
복구 시 실제 프레임 수·임의 이벤트 탐색·보관 기간을 확인합니다. 인덱스만 복사하면 영상은 복구되지 않습니다.

용량 산식은 `3대 × 평균(JPEG+JSON) 바이트 × 녹화 FPS × 86,400 × 보관일`입니다.
예를 들어 평균 100KB+2KB, 2FPS, 30일이면 약 **1.586TB(십진)**이며,
이벤트 추가 프레임·스냅샷·인덱스·파일시스템·백업 여유는 별도입니다. 5FPS면 약 3.966TB입니다.
메타데이터와 스냅샷은 JPEG 용량 상한에 포함되지 않으므로 EBS free/inode 경보와 여유 예산이 필요합니다.
3대×2FPS×30일은 약 1,555만 프레임/3,110만 JPEG·JSON 파일이므로 30일 JPEG 방식의 파일 수 비용도 큽니다.
장기 운영 규모에 따라 구간 MP4와 프레임 메타데이터 인덱스로 확장하는 작업은 남아 있습니다.

## AWS 배포 준비

두 네트워크 방식을 비교했습니다. 고정 현장 라우터가 관리 가능하면 VPN으로 AWS에서 현장 주소에 접근하는 방식이
현재 pull capture와 가장 잘 맞고 추가 트랜스코딩을 피합니다. AWS Site-to-Site VPN은 현장 customer gateway와
AWS gateway·경로 설정이 필요합니다. 이동통신/CGNAT 현장에는 **현장 게이트웨이가 먼저 연결하는 outbound VPN**을
우선 권장합니다. 스마트폰 포트를 인터넷에 직접 공개하지 않습니다.

현장 영상 중계 에이전트는 카메라 가까이에서 재연결/버퍼를 관리하고 outbound TLS로 서버에 보낼 수 있지만
현장 장치 운영, 미디어 relay 서버, 인증·암호화·재연결 및 추가 전송 계층이 필요합니다.
이번 변경에는 전용 push relay를 구현하지 않았습니다. VPN을 사용할 수 없으면 이 계층을 추가해야 합니다.
공인 IP 부여만으로 사설 스마트폰 주소에 접근할 수 있는 것은 아닙니다.
AWS 컨테이너 안에서 직접 각 실제 영상 endpoint의 프레임을 받아볼 때까지 연결 성공으로 판단하지 않습니다.

```bash
# models/best.pt와 선택한 OSNet ONNX 준비, 실제 운영 .env 작성
docker compose -f compose.monitor.yaml config --quiet
docker compose -f compose.monitor.yaml up -d --build
docker compose -f compose.monitor.yaml ps
docker compose -f compose.monitor.yaml logs --tail=100 monitor
```

- `MONITOR_AUTOSTART=true`로 서버 재시작 후 설정된 카메라 감지를 자동 재개합니다.
- 단일 Uvicorn worker를 사용합니다. 여러 worker/컨테이너가 같은 카메라·DVR을 동시에 처리하면 안 됩니다.
- `monitor_data`는 이벤트 SQLite, tracklet/수정 감사, 녹화를 보존합니다. 모델은 읽기 전용 mount입니다.
- 기존 DB와 녹화는 서비스 중단/백업 후 새 volume에 복사하고 **최초 실행 전** `SAFETY_DB_PATH`를 확인합니다.
- 기존 계정 PostgreSQL/RDS를 계속 사용할 수 있습니다. RDS는 TLS `verify-full`과 CA mount를 사용합니다.
  기본 Compose의 PostgreSQL 컨테이너는 개발/단일 호스트 구성이며 운영 DB 백업/고가용성은 별도입니다.
- Docker는 비정상 종료 프로세스를 재시작하며 healthcheck는 생존 상태만 확인합니다. 카메라 장애는 독립 재연결합니다.
  healthcheck가 unhealthy라는 이유만으로 Compose가 컨테이너를 재시작하지는 않으므로 외부 경보가 필요합니다.
- HTTPS는 기존 Nginx/Certbot 또는 ALB에서 종료합니다. `PUBLIC_APP_URL`은 실제 HTTPS origin, `COOKIE_SECURE=true`를 설정합니다.
  브라우저는 동일 출처 WSS/API를 사용합니다. CORS는 그 origin만, POST/PATCH와 WS는 origin 및 세션 인증을 검사합니다.
- `WEB_BIND_ADDRESS=0.0.0.0`은 ALB 경유 배포에서만 설정하고 호스트 8080은 ALB 보안 그룹에서만 허용합니다.
  백엔드 8002·PostgreSQL 5432·카메라 포트·녹화 디렉터리는 외부에 공개하지 않습니다.
- CPU Compose 이미지가 기본입니다. 실측 추론 시간과 대기 시간에 따라 CPU/GPU를 선택해야 하며 특정 EC2 성능/비용을 보장하지 않습니다.
- `.env`는 Git에서 제외하고 접근 권한을 제한합니다. 운영은 Secrets Manager/SSM에서 실행 시 주입합니다.
  영상 주소/암호는 상태 API와 애플리케이션 오류 로그에 포함하지 않습니다.
- CloudWatch Agent/container logs로 로그·CPU·메모리·디스크 free/inode를 수집하고,
  `/api/cameras`의 마지막 수신 시각·추론 대기·처리 지연·녹화 오류·연결 상태를 경보에 연결합니다.
  컨테이너 로그는 10MB×5개로 순환합니다. 카메라의 공급 시간은 알 수 없어 표시 지연은 서버 수신 이후 기준입니다.
- 매일 SQLite backup API로 일관된 DB 백업 또는 중단 상태의 volume 백업을 생성합니다.
  PostgreSQL은 `pg_dump`/RDS snapshot, 영상은 EBS snapshot/S3 암호화 백업과 lifecycle을 별도로 운영합니다.
  복구 훈련에서는 원본 volume을 덮어쓰지 말고 별도 volume/DB로 복원해 로그인·이벤트·과거 프레임을 검증합니다.

AWS 리소스 생성/배포, Docker 이미지 빌드, HTTPS 실제 도메인·쿠키, RDS와의 실접속,
실제 폰 스트림, GPU, 24시간 soak는 이번 환경에서 검증하지 않았습니다.
Compose·Dockerfile·nginx 설정은 준비된 소스이며 해당 환경에서 빌드·연결·복구를 검증한 후 운영해야 합니다.

## 검증 명령과 근거

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend -v
node --test src/frameProtocol.test.js
npm.cmd run build
.\.venv\Scripts\python.exe tools/test_mjpeg.py
# 별도 개발용 패키지: pip install playwright; python -m playwright install chromium
.\.venv\Scripts\python.exe tools/test_browser.py
.\.venv\Scripts\python.exe tools/benchmark_transport.py
```

브라우저/추적/전송 성능 fixture는 모두 합성 데이터이며 운영 이벤트 DB에 쓰지 않습니다.
상세 결과와 수정 파일 목록은 [작업 결과](IMPLEMENTATION-REPORT.md), 원시 합성 측정값은
[benchmark-synthetic.json](benchmark-synthetic.json)에 기록합니다.

근거 문서: [공유 YOLO 스레드 안전성](https://docs.ultralytics.com/guides/yolo-thread-safe-inference/),
[Torchreid/OSNet 공식 저장소](https://github.com/KaiyangZhou/deep-person-reid),
[Torchreid 특징 추출 API](https://kaiyangzhou.github.io/deep-person-reid/user_guide.html#use-torchreid-as-a-feature-extractor-in-your-projects),
[MIT 라이선스](https://github.com/KaiyangZhou/deep-person-reid/blob/master/LICENSE),
[AWS Site-to-Site VPN 구조](https://docs.aws.amazon.com/vpn/latest/s2svpn/how_it_works.html).
