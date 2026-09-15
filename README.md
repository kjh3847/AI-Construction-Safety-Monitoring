# AI Construction Safety Monitoring · 현장지킴

YOLOv8 기반 건설현장 안전장비 착용 모니터링 캡스톤 프로젝트입니다.

## 구현 현황

- React + Vite 화면, 분석 영상 표시, 전체화면, 로컬 영상 미리보기
- FastAPI + YOLOv8로 시험 영상 분석
- SQLite DB 및 이벤트 테이블 생성
- 인원 통계, 작업자별 착용 상태, 실제 이벤트 저장·조회는 연결 예정
- PostgreSQL, AWS EC2·S3, Docker는 기존 계획이며 현재 구현 여부와 구분합니다.

## 백엔드 실행

프로젝트 루트에서 가상환경 생성과 설치를 진행합니다. Python 버전 및 PyTorch 장치 설정은 팀 환경에 맞춰 확인하세요.

```powershell
py -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\backend\.venv\Scripts\python.exe backend/database.py
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

backend/best.pt와 backend/test.mp4는 별도로 준비합니다. 가상환경, 생성된 DB와 시험 영상은 각 컴퓨터에서 관리합니다. GitHub 기존 기록의 nogadaman/weight/best.pt는 그대로 보존했습니다.

# 로컬 개발 및 실행 안내

React + Vite로 만든 안전장비 모니터링 시제품입니다. 화면 수정은 일반 CSS와 React 구성요소로 할 수 있습니다. MUI는 설치하지 않았습니다.

## 실행

1. Node.js 22.12 이상 LTS를 설치합니다. 이 프로젝트는 Node 24 환경에서 작성했습니다.
2. Visual Studio Code의 `파일 > 폴더 열기`에서 이 폴더를 엽니다. Visual Studio에서도 폴더를 열고 터미널에서 같은 명령을 실행할 수 있습니다.
3. 터미널에서 실행합니다. Windows PowerShell 실행 정책 문제를 피하려면 npm.cmd를 사용합니다.

```powershell
npm.cmd install
npm.cmd run dev
```

터미널에 표시된 localhost 주소를 브라우저에서 엽니다. 종료는 Ctrl+C입니다.

```powershell
npm.cmd run build
```

## 파일 안내

- `src/main.jsx`: 화면과 동작. Stat 구성요소를 포함합니다.
- `src/styles.css`: 색상, 크기, 배치, 모바일 화면.
- `src/data.js`: 카메라와 이벤트 예시 데이터. FastAPI 연동용 데이터 형태 설명.
- `public/demo-detection.png`: AI 생성 정지 이미지. 실제 탐지 결과가 아닙니다.

## 구현된 기능

현장 모니터링, 카메라 선택, 로컬 영상 재생, 이벤트 상태·장비별 필터, 이벤트 확인 처리, CSV 내보내기, 알림 기준 브라우저 저장, 반응형 화면.

## 현재 범위

FastAPI의 /video에서 서버의 test.mp4를 YOLO로 분석해 React로 전달합니다. 실시간 웹캠, 로그인, 실제 이벤트 API 및 DB 저장 연동은 아직 구현하지 않았습니다. SQLite 테이블 생성 코드는 backend/database.py에 있습니다. 영상 열기는 컴퓨터 안의 파일을 브라우저에서 재생할 뿐 업로드·분석하지 않습니다. 다른 카메라에는 연결 전 빈 상태를 표시합니다. 현재 프레임과 과거 이벤트는 별개 예시 데이터입니다. 사용자 설정과 확인 상태는 해당 브라우저 localStorage에만 저장됩니다.

## 다음 FastAPI 연결

API 계약을 팀과 확정한 뒤 `src/data.js` 예시 데이터 대신 다음 요청 결과로 상태를 갱신하면 됩니다. 아래 주소는 제안이며 현재 존재하는 API가 아닙니다.

- GET /api/cameras: 카메라 목록
- GET /api/events: 이벤트 목록
- PATCH /api/events/{id}: 확인 여부 저장
- GET /api/cameras/{id}/status: 현재 작업자별 착용 상태
- PUT /api/settings: 서버 알림 설정

실제 영상 전달 방식은 MJPEG/HLS/WebRTC 중 서버 구조에 맞춰 정해야 합니다. 현재 프론트엔드에는 RTSP 주소를 직접 넣지 않습니다. 현재 API 주소는 src/main.jsx의 API_BASE_URL 상수에서 설정합니다. 향후 환경변수로 분리하고, 서버에서 개발용 CORS 허용 출처를 설정하세요. 프론트엔드 환경변수에 비밀키를 넣지 마세요.

참고: https://react.dev/learn , https://vite.dev/guide/

---

## 기존 팀 계획 원문

아래는 GitHub에 있던 초기 계획입니다. 기능·기술·폴더 구조는 목표안을 포함하며, 현재 구현은 위의 구현 현황 및 실제 파일을 기준으로 확인하세요.

# AI Construction Safety Monitoring System

YOLO 기반으로 공사현장 CCTV 영상에서 작업자의 안전복장 착용 여부를 감지하고,
미착용 발생 시 관리자 대시보드에 로그를 저장하는 캡스톤 디자인 프로젝트입니다.

---

## 프로젝트 개요

공사현장 CCTV 영상을 기반으로 작업자를 탐지하고,
안전모 및 안전조끼 착용 여부를 AI가 자동으로 판별합니다.

미착용자가 감지되면 해당 시점의 이미지와 감지 정보를 저장하고,
관리자는 웹 대시보드에서 위반 내역을 확인할 수 있습니다.

---

## 주요 기능

- CCTV / 영상 기반 작업자 탐지
- 안전모 착용 여부 감지
- 안전조끼 착용 여부 감지
- 안전모 미착용 감지
- 안전조끼 미착용 감지
- 위반 발생 시간 및 CCTV 정보 저장
- 위반 이미지 캡처 저장
- 관리자 대시보드에서 위반 로그 조회
- AWS 서버 배포

---

## AI 탐지 클래스

| Class | Description |
|---|---|
| Hardhat | 안전모 착용 |
| NO-Hardhat | 안전모 미착용 |
| Safety Vest | 안전조끼 착용 |
| NO-Safety Vest | 안전조끼 미착용 |
| Person | 작업자 |

---

## 기술 스택

### AI
- Python
- Ultralytics YOLO
- OpenCV
- PyTorch

### Backend
- FastAPI
- Python

### Frontend
- React

### Database
- PostgreSQL

### Cloud
- AWS EC2
- AWS S3
- Docker

---

## 시스템 구조

```text
CCTV / Video
      ↓
   OpenCV
      ↓
     YOLO
      ↓
안전복장 착용 여부 판단
      ↓
    FastAPI
      ↓
 ┌─────────────┐
 │             │
PostgreSQL    AWS S3
위반 로그      캡처 이미지
 │
 ↓
React 관리자 대시보드

데이터 흐름
CCTV 영상 입력
      ↓
프레임 추출
      ↓
YOLO 객체 탐지
      ↓
Person / Hardhat / Safety Vest 탐지
      ↓
미착용 여부 판단
      ↓
위반 이벤트 발생
      ↓
DB 로그 저장 + 이미지 저장
      ↓
관리자 대시보드 출력

데이터베이스 저장 정보
CCTV ID
CCTV 위치
위반 유형
감지 시간
AI Confidence
위반 이미지 경로
처리 상태

예시

CCTV : CAM_01
위반 : NO_HARDHAT
시간 : 2026-09-08 14:32:18
신뢰도 : 0.94
상태 : 미처리

프로젝트 구조
capstone_2_B/

├── ai/
│   ├── dataset/
│   ├── train.py
│   └── best.pt
│
├── backend/
│   └── FastAPI
│
├── frontend/
│   └── React
│
├── database/
│   └── schema.sql
│
├── docs/
│   └── architecture.png
│
└── README.md

팀 역할

AI / Data	데이터 수집, 라벨 검증, YOLO 학습 및 성능 평가
Backend / Video	OpenCV 영상 처리, FastAPI, AI 모델 연동
Frontend	React 관리자 대시보드 및 위반 로그 UI
DB / AWS	PostgreSQL, AWS EC2·S3, Docker 및 배포

```
