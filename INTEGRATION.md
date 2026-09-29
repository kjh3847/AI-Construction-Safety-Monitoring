# 실제 감지 데이터 연결

이 문서는 최초 DB 연동 단계의 기록입니다. 이후 독립 감지 작업·녹화 버퍼·화면 제어로 확장한 현재 동작은 [CCTV.md](CCTV.md)를 참고하세요. 아래의 스트림 종료 동작 등은 이전 버전 설명입니다.

## 실행

프로젝트 루트에서 서로 다른 터미널로 실행합니다. 기존 가상환경과 설치된 npm 패키지를 재사용합니다.

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8002
```

```powershell
npm.cmd run dev
```

http://127.0.0.1:5173 에서 첫 번째 카메라의 **분석 시작**을 누릅니다.
분석 중에만 test.mp4를 읽으며, 페이지 이동/분석 중지로 스트림이 닫히면 분석도 중지합니다.
동시에 한 개의 분석 스트림만 허용합니다. uvicorn은 단일 worker로 실행합니다.
파일 미리보기는 기존처럼 로컬 재생만 수행하며 YOLO 업로드 기능은 아닙니다.

## 실제 모델과 판단 범위

- 실행 모델: `backend/best.pt`
- 확인한 클래스: `Hardhat`, `NO-Hardhat`, `Person`, `Safety Vest`, `NO-Safety Vest`
- `nogadaman/weight/best.pt`는 Mask, Safety Cone, machinery, vehicle 등이 포함된 별도 10클래스 모델이며 서버에서 사용하지 않습니다.
- 루트 `data.yaml`은 `Bad-Buckle-`, `Bad-Loose-`, `Good` 3개 클래스여서 실행 모델과 다릅니다. 런타임은 모델의 `names`를 사용합니다.
- 기존 추론 임계값 `conf=0.4`, CPU, 이미지 크기 640을 유지합니다.
- `NO-Hardhat`, `NO-Safety Vest` 감지 자체만 미착용 의심 이벤트로 저장합니다. 장비가 보이지 않는다는 이유로 미착용을 추론하지 않습니다.
- 작업자별 장비 매칭, 고유 인원 추적, 지속 시간에 따른 위반 확정 기준은 없습니다. 설정 화면의 기존 시간값은 브라우저 저장만 유지하며 분석에 적용되지 않습니다.
- Person 표시는 현재 프레임 박스 수입니다. 고유 작업자 수나 착용률이 아닙니다.
- CAM-01은 시험 영상의 소스 식별자입니다. 실제 현장 CCTV 위치는 확인되지 않아 첫 카메라 이름을 `시험 영상 (test.mp4)`로 표시합니다.

## 저장 구조와 중복 방지

기존 `backend/safety.db`와 `safety_events`를 재사용합니다. 기존 행/열을 삭제하지 않으며 시작 시 필요한 열만 추가합니다.

| 열 | 형식 / 의미 |
|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT |
| camera_name | TEXT NOT NULL, 현재 CAM-01 |
| event_type | TEXT NOT NULL, 모델의 원래 클래스명 |
| model_name | TEXT, best.pt |
| confidence | REAL, 구간 시작 프레임의 해당 클래스 최대 신뢰도 |
| snapshot_path | TEXT, 기존 열 보존, 현재 별도 이미지 저장 없음 |
| review_status | TEXT NOT NULL DEFAULT pending, 확인 시 reviewed |
| created_at | TEXT, DB 저장 시점 UTC ISO 시각 |
| event_key | TEXT, 중복 방지 UNIQUE 인덱스, 기존 행은 NULL |
| source_name | TEXT, test.mp4 |
| video_seconds | REAL, 영상 내 감지 구간 시작 위치 (초) |

같은 카메라·클래스가 계속 검출되면 한 이벤트로 묶습니다. 마지막 검출 이후 **영상 시간 기준 2초 초과** 뒤 다시 검출될 때 새 구간을 시작합니다. 동일 프레임의 여러 박스는 최대 신뢰도로 대표합니다. 이는 저장 중복 방지 기준이며 안전 위반 지속 시간 기준이 아닙니다. 작업자별 이벤트가 아니므로 같은 클래스의 여러 사람을 하나로 묶을 수 있습니다.

영상+모델 파일 SHA-256, 카메라, 클래스, 구간 시작 프레임 번호를 `event_key`로 저장합니다. 같은 입력과 동일한 추론 결과로 처음부터 재생하면 서버 재시작 후에도 중복 삽입되지 않습니다. 추론 결과/구간 경계가 달라지면 다른 키가 될 수 있습니다.

## API와 화면

- `GET /api/events?limit=100&offset=0`: 최신 기록과 DB 전체 total/pending. limit 범위 1~1000.
- `PATCH /api/events/{id}`: 확인 상태를 DB에 저장. 존재하지 않으면 404.
- `GET /api/status`: 분석 상태, 최신 박스·클래스·신뢰도, 감지 갱신 시각, 모델 클래스 목록.
- `GET /video`: MJPEG 분석 영상. 프레임 추론 직후 이벤트 저장.
- CORS: http의 localhost/127.0.0.1 로컬 포트를 허용합니다.
- 화면은 두 API를 2초 간격으로 조회합니다. 로딩/조회 성공이나 기록 없음/연결 실패를 구분하며 실패 시 마지막 기록임을 표시합니다.
- 최근 100건부터 추가 조회하며 화면은 최대 1,000건까지 제공합니다. 전체 기록은 offset API로 조회할 수 있습니다. CSV는 현재 로드된 기록 중 필터 결과를 내보냅니다.
- 기존 DB 테스트 행은 삭제하지 않고 `(기존 테스트 기록)`으로 구분하며 전체 건수에는 포함합니다.
- 화면의 시각은 브라우저 현지 시간이며 CSV는 저장된 UTC 시각입니다. 원본 영상의 실제 촬영 시각은 알 수 없습니다.

## 검증과 확인

```powershell
.\backend\.venv\Scripts\python.exe backend/test_pipeline.py
npm.cmd run build
Invoke-RestMethod http://127.0.0.1:8002/api/events
Invoke-RestMethod http://127.0.0.1:8002/api/status
```

`test_pipeline.py`는 임시 DB에서 원래 스키마의 마이그레이션/기존 행 보존, 연속 감지 중복 방지, 재등장, 재생 중복 방지, 확인 상태, API 및 CORS를 검사합니다. `test_db.py`는 기존의 실제 DB 샘플 삽입 스크립트이므로 검증에 사용하지 않았습니다.

화면에서는 분석 시작 후 감지 기록·신뢰도·건수의 갱신을 확인하고, 확인 버튼을 누른 다음 새로고침해 상태 유지를 확인할 수 있습니다. 미착용 클래스가 감지되지 않은 프레임에서는 이벤트가 늘어나지 않는 것이 정상입니다.

### 이번 실행에서 확인한 결과

- 실제 `/video` HTTP 스트림으로 `test.mp4` 전체 1,826프레임 분석 완료.
- `NO-Hardhat` 6건, `NO-Safety Vest` 3건이 실제 safety.db에 저장되고 API로 조회됨.
- 기존 id=1의 `TEST_NO_HELMET` 행과 기존 값 보존: 전체 10건.
- 같은 영상을 150프레임 재생하여 처음의 미착용 구간을 다시 통과해도 전체 10건 유지.
- 스트림 강제 연결 종료 후 `stopped` 상태와 후속 `/video` 200 응답 확인.
- 임시 DB 기반 테스트 2개 통과: 마이그레이션·보존·중복·확인·API·CORS 검사 포함.
- `npm.cmd run build` 성공, 개발 서버의 변환된 `/src/main.jsx` HTTP 200 확인.
- 브라우저 자동화에 사용 가능한 브라우저가 없어 실제 렌더링·버튼 클릭·빈 상태/서버 실패 화면의 시각 검증은 수행하지 못함. 프론트 빌드와 HTTP 파일 제공 검증을 화면 검증으로 간주하지 않음.
