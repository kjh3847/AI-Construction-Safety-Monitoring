# 중앙 계정 서버: 로컬 PostgreSQL → AWS RDS

## EC2 계정 API 연결 (Duck DNS)

현재 Vite의 /api/auth 및 /api/admin은 https://safety-capstone-2026.duckdns.org 로
전달된다. /api의 나머지 및 /video는 기존 현장 서버 127.0.0.1:8002를 사용한다.
브라우저는 http://localhost:5173 으로 접속한다. 개발 프록시를 통해 같은 출처로
쿠키를 사용하므로 CORS/제3자 쿠키에 의존하지 않는다. 개발용 로컬 HTTP 응답에서만
Secure 속성을 제거하며 EC2와의 연결은 HTTPS 인증서 검증을 유지한다.
운영 HTTPS에서는 Secure 속성을 유지해야 한다.
계정 EC2 PUBLIC_APP_URL은 현재 http://localhost:5173 이다.
메인 웹의 npm run build 결과에는 Vite 개발 프록시가 포함되지 않으므로 실제 웹
배포에는 별도 /api/auth·/api/admin 프록시가 필요하다.
로컬 계정 서버를 써야 할 경우 실행 전 ACCOUNTS_API_URL=http://127.0.0.1:8000 설정.
현장 분석 서버 자체의 인증은 아직 PostgreSQL 연결이 필요하다. 현장 서버를 중앙
인증 API로 검증하도록 바꾸는 작업은 별도다.

## 현재 PC에서 빠르게 실행

`프로젝트 내부 폴더`에서 `.\.venv-accounts\Scripts\python.exe backend\run_accounts.py`.
RDS 암호는 숨김 입력으로 받고, 최초 시스템팀 계정을 대화식으로 생성한다.
Brevo 키는 선택 입력이며 미설정 시 이메일 발송과 관리자 활성화는 완료되지 않는다.
개발용 임시 로그인 우회를 제거했다. 개발 환경에서도 실제 서버 세션이 필요하다.
데스크톱 앱 실행은 `관리자 계정 생성/README.md` 참고.

구현 범위: PostgreSQL 계정·세션·감사 이력, Argon2 비밀번호 해시, 시스템팀 전용
`/admin/accounts`, Brevo 임시 비밀번호 발송, 최초 비밀번호 변경, 로그아웃,
삭제 사유를 기록하는 비활성화. 기존 `0000/0000` 로그인을 제거했다.

영상 분석은 현장 PC에 남는다. 현재 안전 이벤트·영상은 기존 로컬 SQLite 및 파일에
저장된다. 중앙 이벤트 수신 API, PostgreSQL 이벤트 이전, 여러 현장의 영상 중계는
아직 구현되지 않았다. AWS에는 먼저 계정 서버만 배포할 수 있다.

## 로컬 계정 기능 실행

필수: Docker Desktop, Node.js. 프로젝트 루트에서:

1. `.env.example`을 `.env`로 복사하고 비밀번호 및 DATABASE_URL을 일치시킨다.
2. `docker compose -f compose.accounts.yaml up --build -d`
3. `docker compose -f compose.accounts.yaml exec accounts python bootstrap_system.py SYS001 system@example.com`
   프롬프트에서 시스템팀 비밀번호를 입력한다. 기존 사원번호를 덮어쓰지 않는다.
4. `npm install` 후 `npm run dev`, `http://localhost:5173/admin/accounts` 접속.
5. SYS001 로그인. Brevo API 키와 인증된 발신 이메일을 `.env`에 설정한 후
   `docker compose -f compose.accounts.yaml up -d --force-recreate accounts`.
6. 사원번호와 이메일로 관리자 생성. 받은 임시 비밀번호로 로그인하면 변경 화면을 거친다.

API는 동일 출처의 Vite 프록시로 접근한다. localhost와 127.0.0.1을 혼용하지 않는다.
DB 비밀번호/API 키를 VITE_ 환경변수에 넣지 않는다. 프런트에는 비밀을 넣지 않는다.
브라우저에는 HttpOnly 쿠키, DB에는 세션 토큰의 SHA-256 해시만 저장된다.
로그인 5회 실패 시 해당 계정을 15분 잠근다. 운영에는 프록시/WAF의 IP별 속도 제한도 추가한다.

이메일 미설정·전송 실패는 발급 대기로 남으며 로그인할 수 없다. 재전송은 새 임시
비밀번호를 생성한다. API 접수 성공은 실제 수신을 보장하지 않는다. Brevo 반송/배달
웹훅은 아직 연결되지 않았다. 삭제는 물리 삭제 대신 비활성화하고 모든 세션을 제거한다.

## 현장 분석 서버 연결

현장 Python 환경에 `pip install -r backend/requirements-accounts.txt`.
DATABASE_URL은 현장에서 접근 가능한 PostgreSQL 주소로 설정한다. 로컬 개발이면
compose의 postgres 호스트 대신 `127.0.0.1`을 사용한다. PUBLIC_APP_URL은 동일한
프런트 주소, 로컬 HTTP 개발에서만 COOKIE_SECURE=false를 설정한다.
기존 main:app 서버는 8002에서 실행하며 기존 API와 영상은 DB 세션으로 보호한다.
Vite는 기본적으로 계정 API를 EC2 HTTPS 서버로, 영상 API를 8002로 전달한다.
로컬 계정 API 8000을 사용하려면 Vite 실행 전 ACCOUNTS_API_URL을 설정한다.
원격 RDS를 현장 서버에서 쓰려면 VPN 등 비공개 네트워크 경로가 필요하다.
현재 구조는 중앙 DB를 검증하는 현장 백엔드다. 현장 서버가 중앙 인증 API를 통해
검증하도록 바꾸는 작업과 중앙 이벤트 수집은 다음 단계다.

## AWS 계정 서버 배포

1. 동일 VPC에 EC2와 RDS PostgreSQL을 구성한다. RDS 공개 접근은 끈다.
   RDS 보안 그룹의 5432 인바운드는 EC2 보안 그룹에서만 허용한다.
2. RDS에 safety DB와 전용 애플리케이션 사용자를 준비한다. 마스터 계정으로
   서비스를 실행하지 않는다. 현재 초기화에는 테이블 생성 권한이 필요하다.
3. RDS CA 인증서를 배포하고 DATABASE_URL에 sslmode=verify-full과 sslrootcert를
   설정한다. 컨테이너에는 인증서 디렉터리를 읽기 전용으로 마운트한다.
4. EC2에서 Docker 이미지를 빌드하고 `.env` 대신 서버 비밀 설정으로 환경변수를
   전달한다. 컨테이너 8000 포트는 127.0.0.1에만 바인딩한다.
   로컬 compose는 postgres까지 띄우므로 운영 배포에는 사용하지 않는다.
5. 시스템팀 계정은 컨테이너 내 bootstrap_system.py로 한 번 생성한다.
6. `npm run build` 결과 dist를 /var/www/safety에 배포하고 Nginx 설정 예시를
   적용한다. ALB + ACM 또는 Nginx 인증서로 HTTPS를 제공한다.
   PUBLIC_APP_URL=https://실제도메인, COOKIE_SECURE=true로 설정한다.
7. RDS 자동 백업·로그·비용 알림을 설정한다. AWS 자원은 실제 생성하지 않았다.

계정 서버만 배포한 경우 `/admin/accounts`와 로그인은 가능하지만 클라우드
대시보드에는 현장 영상이 연결되지 않는다. Nginx 예시는 이 범위를 명시한다.

## 검증

PostgreSQL 테스트 전용 DB에 TEST_DATABASE_URL을 설정하고:
`cd backend` → `python -m unittest test_identity.py`.
테스트는 accounts, account_sessions, account_audit 테이블을 삭제하므로 운영 DB 금지.
테스트 DB 이름은 `_test`로 끝나야 한다.
프런트 빌드: `npm run build`.

현재 검증 결과: 프런트 빌드 통과, Python 구문 검사 통과, DB 없이 실행하는
비밀번호 생성·해시·정책·출처 검사 4개 통과. PostgreSQL 통합 테스트 3개는
TEST_DATABASE_URL이 없어 실행하지 못했다. 프로젝트 `.venv-accounts`에는
계정 서버 의존성을 설치했다. 이 환경에는 Docker Desktop이 확인되지 않았다.

참고: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_VPC.Scenarios.html
https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
https://developers.brevo.com/docs/send-a-transactional-email
