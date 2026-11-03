"""Interactive local launcher. Secrets are prompted, never written to disk."""
import os
from getpass import getpass
from pathlib import Path
import psycopg
from psycopg.conninfo import make_conninfo
import uvicorn


def main():
    root = Path(__file__).resolve().parent.parent
    if not os.getenv('DATABASE_URL'):
        host = input('RDS endpoint [safety-dev-db.cd2e804cyc02.ap-northeast-2.rds.amazonaws.com]: ').strip()
        host = host or 'safety-dev-db.cd2e804cyc02.ap-northeast-2.rds.amazonaws.com'
        certificate = root / 'global-bundle.pem'
        if not certificate.is_file():
            raise SystemExit('global-bundle.pem 인증서가 프로젝트 폴더에 없습니다.')
        os.environ['DATABASE_URL'] = make_conninfo(host=host, port=5432, dbname='safety',
            user=input('DB user [postgres]: ').strip() or 'postgres',
            password=getpass('DB password: '), sslmode='verify-full', sslrootcert=str(certificate))
    os.environ.setdefault('PUBLIC_APP_URL', 'http://localhost:5173')
    os.environ.setdefault('COOKIE_SECURE', 'false')  # loopback HTTP development only
    from identity_db import init_identity, connect
    from identity import hasher, validate_password
    init_identity()
    with connect() as db:
        exists = db.execute("SELECT 1 FROM accounts WHERE role='system' AND status='active' LIMIT 1").fetchone()
    if not exists:
        print('최초 시스템팀 계정을 만듭니다. 메인 로그인과 계정 발급 프로그램에서 공통으로 사용합니다.')
        from identity import AccountInput
        account = AccountInput(employee_id=input('System employee ID: ').strip(), email=input('System email: ').strip())
        password = getpass('System password (11+ chars, upper/lower/digit/symbol): ')
        validate_password(password)
        if password != getpass('Confirm system password: '):
            raise SystemExit('비밀번호 확인이 일치하지 않습니다.')
        with connect() as db:
            db.execute("INSERT INTO accounts(employee_id,email,password_hash,role,status,must_change_password) VALUES (%s,%s,%s,'system','active',FALSE)",
                       (account.employee_id, str(account.email), hasher.hash(password)))
    if not os.getenv('BREVO_API_KEY'):
        key = getpass('Brevo API key (Enter to skip email setup): ').strip()
        if key:
            os.environ['BREVO_API_KEY'] = key
            os.environ['BREVO_SENDER_EMAIL'] = input('Brevo verified sender email: ').strip()
    print('계정 API: http://127.0.0.1:8000 | 로그인 화면: http://localhost:5173')
    print('이 터미널은 서버 실행 중 열어두세요. 종료: Ctrl+C')
    uvicorn.run('account_server:app', host='127.0.0.1', port=8000)


if __name__ == '__main__':
    try:
        main()
    except psycopg.Error:
        raise SystemExit('DB 연결/저장 실패: 서버 상태, IP 허용 규칙, DB 계정을 확인하세요.') from None
