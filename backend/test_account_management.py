"""Account lifecycle policy tests; PostgreSQL integration tests are separate."""
import unittest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from identity import delete_account, disable, DisableInput, system_user


class ManagementTests(unittest.TestCase):
    def test_regular_admin_cannot_manage_accounts(self):
        with self.assertRaises(HTTPException) as error:
            system_user({'role':'admin','must_change_password':False})
        self.assertEqual(error.exception.status_code,403)

    def test_delete_requires_disabled_account(self):
        for row, code in [({'role':'system','status':'disabled'},403),
                          ({'role':'admin','status':'active'},409),
                          ({'role':'admin','status':'pending'},409), (None,404)]:
            with self.subTest(row=row), patch('identity.connect') as connect:
                db=connect.return_value.__enter__.return_value
                db.execute.return_value.fetchone.return_value=row
                with self.assertRaises(HTTPException) as error:
                    delete_account('001',DisableInput(reason='퇴사'),{'employee_id':'SYS'})
                self.assertEqual(error.exception.status_code,code)
                self.assertFalse(any('DELETE FROM accounts' in call.args[0] for call in db.execute.call_args_list))

    def test_disable_protects_system_account(self):
        with patch('identity.connect') as connect:
            db=connect.return_value.__enter__.return_value
            db.execute.return_value.fetchone.return_value={'role':'system'}
            with self.assertRaises(HTTPException) as error:
                disable('SYS',DisableInput(reason='test'),{'employee_id':'SYS'})
            self.assertEqual(error.exception.status_code,403)

    def test_empty_reason_rejected_before_database_access(self):
        for operation in (disable,delete_account):
            with patch('identity.connect') as connect, self.assertRaises(HTTPException):
                operation('001',DisableInput(reason='   '),{'employee_id':'SYS'})
            connect.assert_not_called()

    def test_delete_preserves_audit_and_revokes_sessions(self):
        with patch('identity.connect') as connect:
            db=connect.return_value.__enter__.return_value
            db.execute.return_value.fetchone.return_value={'role':'admin','status':'disabled'}
            result=delete_account('001',DisableInput(reason='퇴사'),{'employee_id':'SYS'})
            statements=[call.args[0] for call in db.execute.call_args_list]
            self.assertTrue(any('DELETE FROM account_sessions' in sql for sql in statements))
            self.assertTrue(any('INSERT INTO account_audit' in sql for sql in statements))
            self.assertTrue(any('DELETE FROM accounts WHERE' in sql for sql in statements))
            self.assertIn('영구 삭제',result['message'])


if __name__ == '__main__':
    unittest.main()
