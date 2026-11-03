"""One-time system-team account setup; no public registration endpoint."""
import argparse
from getpass import getpass
from pydantic import TypeAdapter, EmailStr
from identity import hasher, validate_password
from identity_db import connect, init_identity

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('employee_id')
    parser.add_argument('email')
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email))
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', args.employee_id):
        parser.error('Invalid employee ID')
    password = getpass('System account password: ')
    validate_password(password)
    if password != getpass('Confirm password: '):
        parser.error('Passwords do not match')
    init_identity()
    with connect() as db:
        db.execute("INSERT INTO accounts(employee_id,email,password_hash,role,status,must_change_password) VALUES (%s,%s,%s,'system','active',FALSE)",
                   (args.employee_id, email, hasher.hash(password)))
    print('System account created.')
