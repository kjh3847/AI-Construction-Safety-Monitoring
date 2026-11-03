# 로그인·카메라 통합 검토 기록 (2026-11-03)

## 기준과 배치

- 공통 원본 `072dd66d05215bfb3384f1a1afcaec0cea38cc69`, 트리 `beaa564962ac69f6796f1c05dd1b03873204425d` 재확인.
- 팀원 최신 기준 `origin/main`: `82282006640619c147e1739ab1282a974270ddec`.
  다른 브랜치 `frontend-login-wip`는 더 오래된 `fdde397`이다.
- ZIP 기존 파일 9개 변경, 신규 앱 파일 24개 및 관리자 프로그램 6개 확인.
  나머지 원본 파일 33개는 줄바꿈 정규화 후 동일하며 누락은 없다.
  원본과 일관되지만 ZIP에 Git 이력이 없어 시작 출처를 독립적으로 증명하지는 못한다.
- 제시된 `deploy/CHANGES-SINCE-2026-10-13.md`는 전달된 작업본에 없다.
- 내부 앱 폴더가 저장소 루트에 대응하고 `관리자 계정 생성/`은 루트 바로 아래에 배치했다.
  원본 ZIP, 계정 정보 문서, 기존 EXE는 수정하거나 삭제하지 않았다.

## 병합 결정

공통 원본 대비 양쪽 diff를 검토하고 3방향 병합했다. DB의 로컬 track_id 제거와
원격 스키마 복구가 충돌했으므로 원격 스키마를 유지했다. 로컬 monitor.py의 predict 전환은
계정 변경이 아니어서 반영하지 않고 원격 BoT-SORT, track_id, LatestFrameReader를 유지했다.
main.py의 로컬 2채널 시험 파일 구성 대신 원격 3채널과 각 YOLO 모델을 유지했다.
database.py, monitor.py, live_capture.py, src/data.js 및 팀원 iPhone 스크립트·문서는 원격과 동일하다.

기존 영상 API에 인증·출처 검사를 결합했다. 웹에 로그인, 최초 비밀번호 변경, 계정 관리,
프로필·로그아웃, 쿠키를 포함하는 동일 출처 영상·이벤트 요청을 추가했다. 개발용 임시 로그인
우회는 제거했다. 관리자 EXE 빌드는 루트 가상환경을 우선하고 -PythonPath 지정도 지원한다.
README의 실행 경로를 수정했다. base64 업로드 명령에 들어 있던 과거 API 소스는 현재 파일을
직접 올리는 수동 배포 안내로 대체했다. 이번 작업에서 서버 배포는 수행하지 않았다.

## 검증

운영 EC2/RDS, 계정, Brevo, DuckDNS는 변경하지 않았다. 별도 Python 3.12 환경에서
TEST_DATABASE_URL과 DATABASE_URL을 비우고 다음을 실행했다.

```powershell
cd backend
python -m unittest test_auth_video_integration test_identity test_account_management test_origins test_database_init test_live_capture test_event_facts test_person_dedup test_person_safety test_pipeline test_recording test_sustained_warning -v
cd "../관리자 계정 생성"
python -m unittest test_api_client -v
cd ..
npm.cmd ci --ignore-scripts --no-audit --no-fund
npm.cmd run build
```

- 백엔드 44개 중 41개 통과, 전용 PostgreSQL 테스트 DB가 필요한 3개 건너뜀.
- 관리자 클라이언트 6개 통과. 전체 47개 통과, 3개 건너뜀.
- 웹 빌드 및 PowerShell 빌드 스크립트 구문 검사 통과.
- 새 통합 테스트: 별도 계정/영상 ASGI 앱, 가짜 PostgreSQL 세션 저장소와 YOLO,
  임시 SQLite/프레임 파일 사용. 실제 인증 핸들러로 로그인 후 3채널 프레임·이벤트 조회,
  일반 관리자 계정 관리 403, 잘못된 Origin 차단, 계정 앱 로그아웃 후 영상 앱에 남은
  쿠키의 401을 확인했다. 실제 RDS·웹캠·브라우저 영상 검증은 아니다.
- 영상 API 회귀 테스트 3개는 명시적 테스트 사용자·가짜 모델을 쓰는 격리 fixture로 수정했다.
  PostgreSQL 접근을 금지하며 실제 인증 의존성은 새 통합 테스트에서 검증한다.
- 실제 모델·영상이 필요한 test_monitor 및 기존 2채널 가정의 test_sources는 미실행.
  실제 YOLO 추론, RDS 접속, Brevo 발송, EXE 재빌드·실행도 미확인이다.
- 계정 requirements 범위 내 패키지를 설치했다. 영상 requirements 전체의 고정 버전
  설치와 실제 YOLO 실행 환경 검증은 수행하지 않았다.

## 실제 실행에 필요한 설정

1. 로컬 영상 서버에도 계정 서버와 **동일 PostgreSQL DB**의 DATABASE_URL과
   PUBLIC_APP_URL=http://localhost:5173을 전달해야 한다. Start-iPhone.ps1은 카메라 주소만
   읽고 .env의 DB 설정은 자동 로드하지 않는다. 실행 PowerShell 환경에 별도로 전달한다.
   쿠키 프록시만으로 RDS 네트워크 연결이 생기지 않는다. 기존 승인된 접속 경로가 필요하며
   이번 작업에서 RDS 공개 접근·보안 그룹을 변경하지 않았다.
2. RDS TLS는 sslmode=verify-full과 sslrootcert에 로컬 global-bundle.pem 절대 경로를 사용한다.
   이 PEM은 공개 RDS CA 인증서이며 개인키가 아니다. 접속 비밀값은 커밋하지 않는다.
3. 영상 서버 시작은 init_identity()를 호출하므로 테이블 초기화 권한이 필요하다.
   이 작업에서 운영 스키마 초기화를 실행하지 않았다. 운영 변경은 별도 검토한다.
4. 브라우저는 http://localhost:5173을 사용한다. /api/auth·/api/admin은 EC2 HTTPS,
   나머지 /api와 /video는 127.0.0.1:8002로 프록시한다. VITE_API_BASE_URL은 비워
   동일 출처를 유지한다. ACCOUNTS_API_URL은 Vite 실행 프로세스 환경변수다.
   localhost와 127.0.0.1을 오가면 브라우저 쿠키가 분리된다.
5. .env.local의 CAM-01 스트림 URL, 모델 및 CAM-02/03 입력은 팀원 문서·기존 구조에 맞춰
   현장에서 설정한다. 카메라 자격증명은 업로드하지 않는다.
6. npm run build 결과에는 개발 프록시가 없다. 정적 배포에는 계정 API와 현장 영상 서버로
   연결하는 동일 출처 리버스 프록시가 필요하다. 계정 전용 Nginx 예시는 영상 중계가 아니다.

## EXE 배포

ZIP의 관리자 계정 생성/dist/SafetyAccountAdmin-cloud.exe는 원본에 보존했다.
소스 PR에는 실행 파일·빌드 결과를 넣지 않는다. 검토 후 이 브랜치 소스로 재빌드하고
GUI·HTTPS 동작을 검증한 뒤 GitHub Release 첨부 파일 등으로 분리 배포할 수 있다.
현재 EXE가 이 PR 소스와 일치한다고 보장하지 않으며 Release도 게시하지 않았다.
EXE는 HTTP API 클라이언트만 포함하고 DB 암호·Brevo 키는 서버에만 둔다.
