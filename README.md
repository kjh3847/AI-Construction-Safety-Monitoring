# 현장지킴 프론트엔드

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

YOLO 실행, 실제 CCTV 스트리밍, 로그인, 서버 저장은 구현하지 않았습니다. 영상 열기는 컴퓨터 안의 파일을 브라우저에서 재생할 뿐 업로드·분석하지 않습니다. 다른 카메라에는 연결 전 빈 상태를 표시합니다. 현재 프레임과 과거 이벤트는 별개 예시 데이터입니다. 사용자 설정과 확인 상태는 해당 브라우저 localStorage에만 저장됩니다.

## 다음 FastAPI 연결

API 계약을 팀과 확정한 뒤 `src/data.js` 예시 데이터 대신 다음 요청 결과로 상태를 갱신하면 됩니다. 아래 주소는 제안이며 현재 존재하는 API가 아닙니다.

- GET /api/cameras: 카메라 목록
- GET /api/events: 이벤트 목록
- PATCH /api/events/{id}: 확인 여부 저장
- GET /api/cameras/{id}/status: 현재 작업자별 착용 상태
- PUT /api/settings: 서버 알림 설정

실제 영상 전달 방식은 MJPEG/HLS/WebRTC 중 서버 구조에 맞춰 정해야 합니다. 현재 프론트엔드에는 RTSP 주소를 직접 넣지 않습니다. API 주소는 VITE_API_BASE_URL 환경변수로 관리하고, 서버에서 개발용 CORS 허용 출처를 설정하세요. 프론트엔드 환경변수에 비밀키를 넣지 마세요.

참고: https://react.dev/learn , https://vite.dev/guide/
