"""Integration tests. Explicit disposable PostgreSQL *_test database only."""
import os
import unittest
from urllib.parse import urlparse
from unittest.mock import patch

TEST_URL = os.getenv('TEST_DATABASE_URL', '')
if TEST_URL:
    if not urlparse(TEST_URL).path.endswith('_test'):
        raise RuntimeError('TEST_DATABASE_URL must reference a disposable *_test database')
    os.environ['DATABASE_URL'] = TEST_URL
os.environ['PUBLIC_APP_URL'] = 'http://testserver'
os.environ['COOKIE_SECURE'] = 'false'

from fastapi.testclient import TestClient
from account_server import app
from identity import hasher, temporary_password
from identity_db import connect, init_identity


@unittest.skipUnless(TEST_URL, 'Set TEST_DATABASE_URL to a disposable PostgreSQL *_test DB')
class AccountTests(unittest.TestCase):
    def setUp(self):
        with connect() as db:
            db.execute('DROP TABLE IF EXISTS account_sessions, account_audit, accounts')
        init_identity()
        with connect() as db:
            db.execute("INSERT INTO accounts(employee_id,email,password_hash,role,status,must_change_password) VALUES ('SYS','sys@example.com',%s,'system','active',FALSE)", (hasher.hash('System1234!'),))
        self.client = TestClient(app)
        self.client.headers['origin'] = 'http://testserver'

    def login(self, employee_id='SYS', password='System1234!'):
        return self.client.post('/api/auth/login', json={'employee_id': employee_id, 'password': password})

    def test_cookie_logout_and_origin(self):
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        self.assertIn('HttpOnly', self.client.cookies.get('safety_session') and self.login().headers['set-cookie'])
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/logout', headers={'origin': 'https://other.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_pending_duplicate_resend_change_and_disable(self):
        self.login()
        with patch.dict(os.environ, {'BREVO_API_KEY': '', 'BREVO_SENDER_EMAIL': ''}):
            self.assertEqual(self.client.post('/api/admin/accounts', json={'employee_id': '001', 'email': 'admin@example.com'}).status_code, 503)
        self.assertEqual(self.login('001', 'anything').status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/admin/accounts', json={'employee_id': '001', 'email': 'admin@example.com'}).status_code, 409)
        with patch.dict(os.environ, {'BREVO_API_KEY': 'test', 'BREVO_SENDER_EMAIL': 'sys@example.com'}), patch('identity.httpx.post') as send, patch('identity.temporary_password', return_value='Temp123456!'):
            self.assertEqual(self.client.post('/api/admin/accounts/001/resend').status_code, 200)
            send.assert_called_once()
        self.assertTrue(self.login('001', 'Temp123456!').json()['must_change_password'])
        self.assertEqual(self.client.get('/api/admin/accounts').status_code, 403)
        self.assertEqual(self.client.post('/api/auth/password', json={'current_password':'Temp123456!', 'new_password':'Newpass1234!', 'confirm_password':'Newpass1234!'}).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertFalse(self.login('001', 'Newpass1234!').json()['must_change_password'])
        admin_cookie = self.client.cookies.get('safety_session')
        self.login()
        self.assertEqual(self.client.post('/api/admin/accounts/001/disable', json={'reason':'퇴사'}).status_code, 200)
        self.client.cookies.clear()
        self.client.cookies.set('safety_session', admin_cookie)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.login('001', 'Newpass1234!').status_code, 401)

    def test_lockout_and_validation(self):
        for _ in range(5):
            self.assertEqual(self.login(password='wrong').status_code, 401)
        self.assertEqual(self.login().status_code, 401)
        with connect() as db:
            db.execute("UPDATE accounts SET locked_until=now()-interval '1 minute' WHERE employee_id='SYS'")
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.post('/api/admin/accounts', json={'employee_id':'002','email':'invalid'}).status_code, 422)


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self):
        hashed = hasher.hash('Example1234!')
        self.assertTrue(hashed.startswith('$argon2id$'))
        self.assertTrue(hasher.verify('Example1234!', hashed))
        self.assertFalse(hasher.verify('wrong', hashed))

    def test_origin_guard(self):
        client = TestClient(app)
        self.assertEqual(client.post('/api/auth/login', json={'employee_id':'SYS','password':'test'}).status_code, 403)

    def test_password_rules(self):
        from identity import validate_password
        from fastapi import HTTPException
        for password in ['short', 'alllowercase123!', 'ALLUPPERCASE123!', 'NoDigitsHere!', 'NoSpecial1234']:
            with self.assertRaises(HTTPException):
                validate_password(password)
        validate_password('Example1234!')

    def test_generated_password(self):
        for _ in range(100):
            password = temporary_password()
            self.assertEqual(len(password), 11)
            self.assertTrue(any(c.islower() for c in password))
            self.assertTrue(any(c.isupper() for c in password))
            self.assertTrue(any(c.isdigit() for c in password))
            self.assertTrue(any(c in '!@#$%&*?' for c in password))


if __name__ == '__main__':
    unittest.main()
