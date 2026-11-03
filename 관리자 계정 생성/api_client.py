"""Desktop client: account credentials stay on the API server, never in this app."""
from urllib.parse import urlparse
import ssl
import certifi
import httpx


class AccountClient:
    def __init__(self, base_url, origin):
        url = urlparse(base_url)
        if url.scheme not in ('http', 'https') or not url.hostname:
            raise ValueError('올바른 API 주소를 입력하세요.')
        if url.scheme != 'https' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('원격 서버에는 HTTPS 주소를 사용하세요.')
        # Use the bundled CA file explicitly: a parent process may provide an
        # SSL_CERT_FILE path that does not exist on the EXE user's computer.
        context = ssl.create_default_context(cafile=certifi.where())
        self.http = httpx.Client(base_url=base_url.rstrip('/'), verify=context,
                                 headers={'Origin': origin.rstrip('/')}, timeout=25)

    def request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.RequestError:
            raise ValueError('서버에 연결하지 못했습니다. API 주소와 서버 실행 상태를 확인하세요.') from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError('API 서버의 응답 형식이 올바르지 않습니다. 서버 주소를 확인하세요.') from None
        if not response.is_success:
            detail = data.get('detail')
            raise ValueError(detail if isinstance(detail, str) else '입력값을 확인하세요.')
        return data

    def login(self, employee_id, password):
        user = self.request('POST', '/api/auth/login', json={'employee_id': employee_id, 'password': password})
        if user['role'] != 'system':
            self.request('POST', '/api/auth/logout')
            raise ValueError('시스템팀 계정으로 로그인하세요.')
        return user

    def close(self):
        self.http.close()
