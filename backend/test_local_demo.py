"""Local demo has real isolated sessions and never accesses production accounts."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import database
import local_demo
from account_server import attach_identity


class LocalDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.data=self.root/'.local-run'/'demo'
        self.environment=patch.dict(os.environ,{
            'LOCAL_DEMO_ENABLED':'true','DATABASE_URL':'','PUBLIC_APP_URL':'http://localhost:5173',
            'SAFETY_DB_PATH':str(self.data/'events.sqlite3'),'MONITOR_STORAGE_DIR':str(self.data/'recordings'),
            'REID_MODEL_PATH':'','REID_PRELOAD':'false','MONITOR_AUTOSTART':'false',
            'CAMERA_SOURCE':'','CAMERA_01_SOURCE':'','CAMERA_02_SOURCE':'','CAMERA_03_SOURCE':''})
        self.environment.start()
        self.root_patch=patch.object(local_demo,'ROOT',self.root);self.root_patch.start()
        local_demo.initialize()

    def tearDown(self):
        self.root_patch.stop();self.environment.stop();self.temp.cleanup()

    def client(self,address='127.0.0.1'):
        app=FastAPI();attach_identity(app,local_demo=True)
        return TestClient(app,base_url='http://localhost:5173',client=(address,12345))

    def test_session_login_logout_and_cookie_separation(self):
        with self.client() as client:
            client.headers['origin']='http://localhost:5173'
            self.assertEqual(client.get('/api/auth/me').status_code,401)
            response=client.post('/api/auth/local-demo')
            self.assertEqual(response.status_code,200)
            self.assertIn('safety_local_demo=',response.headers['set-cookie'])
            self.assertIn('HttpOnly',response.headers['set-cookie'])
            self.assertNotIn('safety_session=',response.headers['set-cookie'])
            self.assertEqual(client.get('/api/auth/me').json()['employee_id'],'LOCAL_DEMO')
            self.assertEqual(client.post('/api/auth/logout').status_code,200)
            self.assertEqual(client.get('/api/auth/me').status_code,401)

    def test_production_database_or_external_origin_refused(self):
        with patch.dict(os.environ,{'DATABASE_URL':'postgresql://not-used.invalid/db'}):
            with self.assertRaises(RuntimeError):local_demo.validate_configuration()
        with patch.dict(os.environ,{'PUBLIC_APP_URL':'https://outside.invalid'}):
            with self.assertRaises(RuntimeError):local_demo.validate_configuration()
        with patch.dict(os.environ,{'SAFETY_DB_PATH':str(self.root/'existing.db')}):
            with self.assertRaises(RuntimeError):local_demo.validate_configuration()

    def test_remote_peer_host_and_wrong_origin_denied(self):
        with self.client('192.0.2.1') as client:
            self.assertEqual(client.post('/api/auth/local-demo',headers={'origin':'http://localhost:5173'}).status_code,403)
        with self.client() as client:
            self.assertEqual(client.post('/api/auth/local-demo',headers={'origin':'http://evil.invalid'}).status_code,403)
            self.assertEqual(client.get('/api/auth/me',headers={'host':'evil.invalid'}).status_code,403)

    def test_normal_auth_router_never_exposes_demo_login(self):
        app=FastAPI();attach_identity(app)
        with TestClient(app,base_url='http://localhost:5173') as client:
            self.assertEqual(client.post('/api/auth/local-demo',headers={'origin':'http://localhost:5173'}).status_code,404)

    def test_real_app_starts_without_postgres_and_keeps_all_cameras_empty(self):
        previous=sys.modules.pop('main',None)
        try:
            with patch.object(database,'DB_PATH',self.data/'events.sqlite3'), \
                    patch('identity_db.connect',side_effect=AssertionError('Production DB must not be used')):
                main=importlib.import_module('main')
                with TestClient(main.app,base_url='http://localhost:5173',client=('127.0.0.1',12345)) as client:
                    client.headers['origin']='http://localhost:5173'
                    self.assertEqual(client.get('/health').status_code,200)
                    self.assertTrue(client.get('/api/runtime').json()['local_demo'])
                    self.assertEqual(client.get('/api/cameras').status_code,401)
                    client.post('/api/auth/local-demo')
                    cameras=client.get('/api/cameras').json()['cameras']
                    self.assertEqual(len(cameras),3)
                    self.assertTrue(all(c['state']=='unconfigured' for c in cameras))
                    self.assertEqual(client.post('/api/monitor/start?camera_id=all').status_code,200)
                    self.assertEqual(client.get('/api/events').json()['events'],[])
                    self.assertEqual(client.get('/api/admin/accounts').status_code,404)
        finally:
            sys.modules.pop('main',None)
            if previous is not None:sys.modules['main']=previous
