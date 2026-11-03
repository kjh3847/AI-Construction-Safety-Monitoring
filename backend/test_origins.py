import unittest
from account_server import origin_allowed


class OriginTests(unittest.TestCase):
    def test_loopback_aliases(self):
        for origin in ['http://localhost:5173', 'http://127.0.0.1:5173', 'http://[::1]:5173']:
            self.assertTrue(origin_allowed(origin, 'http://localhost:5173'))

    def test_other_origins_stay_blocked(self):
        for origin in ['', 'null', 'http://localhost:5174', 'https://localhost:5173',
                       'http://evil.example:5173', 'http://localhost.evil.example:5173',
                       'http://localhost:5173/path', 'http://localhost:invalid']:
            self.assertFalse(origin_allowed(origin, 'http://localhost:5173'))

    def test_production_exact_match_only(self):
        self.assertTrue(origin_allowed('https://safety.example', 'https://safety.example'))
        self.assertFalse(origin_allowed('http://localhost:5173', 'https://safety.example'))
        self.assertFalse(origin_allowed('https://evil.example', 'https://safety.example'))


if __name__ == '__main__':
    unittest.main()
