import unittest
from unittest.mock import patch
import httpx
from api_client import AccountClient


class ClientTests(unittest.TestCase):
    def test_missing_environment_ca_does_not_break_client(self):
        with patch.dict('os.environ', {'SSL_CERT_FILE':'C:/missing-ca-file.pem', 'SSL_CERT_DIR':'C:/missing-ca-directory'}):
            client = AccountClient('http://127.0.0.1:8000', 'http://localhost:5173')
            client.close()

    def client(self, handler):
        client = AccountClient('http://127.0.0.1:8000', 'http://localhost:5173')
        client.http.close()
        client.http = httpx.Client(base_url='http://127.0.0.1:8000',
            headers={'Origin':'http://localhost:5173'}, transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def test_remote_requires_https(self):
        with self.assertRaises(ValueError):
            AccountClient('http://example.com', 'https://example.com')

    def test_login_cookie_is_reused(self):
        def handler(request):
            self.assertEqual(request.headers['origin'], 'http://localhost:5173')
            if request.url.path.endswith('/login'):
                return httpx.Response(200, json={'role':'system','employee_id':'SYS'},
                    headers={'set-cookie':'safety_session=abc; HttpOnly; Path=/'})
            self.assertIn('safety_session=abc', request.headers['cookie'])
            return httpx.Response(200, json={'accounts':[]})
        client = self.client(handler)
        client.login('SYS', 'example')
        self.assertEqual(client.request('GET','/api/admin/accounts'), {'accounts':[]})

    def test_admin_role_rejected_and_logged_out(self):
        paths = []
        def handler(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={'role':'admin'})
        with self.assertRaisesRegex(ValueError, '시스템팀'):
            self.client(handler).login('001', 'example')
        self.assertEqual(paths, ['/api/auth/login', '/api/auth/logout'])

    def test_duplicate_error_is_shown(self):
        client = self.client(lambda request: httpx.Response(409, json={'detail':'이미 등록된 사원번호입니다.'}))
        with self.assertRaisesRegex(ValueError, '사원번호'):
            client.request('POST','/api/admin/accounts',json={'employee_id':'001','email':'test@example.com'})

    def test_unexpected_response(self):
        client = self.client(lambda request: httpx.Response(502, text='<html>Bad gateway</html>'))
        with self.assertRaisesRegex(ValueError, '응답 형식'):
            client.request('GET', '/api/admin/accounts')


if __name__ == '__main__':
    unittest.main()
