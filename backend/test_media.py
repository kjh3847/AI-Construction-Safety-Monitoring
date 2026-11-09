import asyncio
import os
import struct
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock

from fastapi import HTTPException
from media_auth import MediaIdentity,authorized
from media_gateway import MediaGateway
from rtsp_clock import H264RTP,rtp_payload,RTSPClockCapture


class StreamPermissionTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'CAMERA_01_PUBLISH_USER':'one','CAMERA_01_PUBLISH_PASSWORD':'fixture1',
            'CAMERA_02_PUBLISH_USER':'two','CAMERA_02_PUBLISH_PASSWORD':'fixture2',
            'MEDIA_AI_PASSWORD':'ai-fixture','MEDIA_WEB_PASSWORD':'web-fixture','MEDIA_CONTROL_PASSWORD':'control-fixture'})
        self.env.start()
    def tearDown(self):self.env.stop()
    def allowed(self,**values):return authorized(MediaIdentity(**values))
    def test_publish_is_scoped_to_one_path_and_not_read(self):
        base=dict(user='one',password='fixture1',protocol='rtmp',path='cam01',action='publish')
        self.assertTrue(self.allowed(**base))
        for changed in ({'path':'cam02'},{'action':'read'},{'protocol':'webrtc'},{'password':'wrong'},{'path':'cam04'},{'user':'외부'}):
            self.assertFalse(self.allowed(**{**base,**changed}))
    def test_ai_web_and_api_roles_are_separate(self):
        self.assertTrue(self.allowed(user='ai_reader',password='ai-fixture',protocol='rtsp',path='cam02',action='read'))
        self.assertFalse(self.allowed(user='ai_reader',password='ai-fixture',protocol='webrtc',path='cam02',action='read'))
        self.assertTrue(self.allowed(user='web_gateway',password='web-fixture',protocol='webrtc',path='cam03',action='read'))
        self.assertFalse(self.allowed(user='web_gateway',password='web-fixture',protocol='rtmp',path='cam03',action='publish'))
        self.assertTrue(self.allowed(user='control',password='control-fixture',action='api'))
        self.assertFalse(self.allowed(user='',password='',protocol='webrtc',path='cam01',action='read'))


class RTPTests(unittest.TestCase):
    def test_coalesced_rtsp_response_and_rtp_preserve_wire_order(self):
        payload=b'frame-data'
        response=b'RTSP/1.0 200 OK\r\nContent-Length: 3\r\n\r\nsdp'
        wire=response+b'$\x00'+struct.pack('!H',len(payload))+payload
        capture=RTSPClockCapture.__new__(RTSPClockCapture)
        capture.buffer=bytearray()
        capture.sock=SimpleNamespace(recv=lambda size:wire)
        headers,body=capture._message()
        self.assertEqual(body,b'sdp')
        self.assertEqual(capture._message(),(0,payload))
        self.assertEqual(capture.buffer,bytearray())

    def packet(self,payload,marker=False,timestamp=123):
        return struct.pack('!BBHII',128,96+(128 if marker else 0),1,timestamp,42)+payload
    def test_fragmentation_preserves_timestamp_and_annexb(self):
        decoder=H264RTP()
        self.assertIsNone(decoder.feed(self.packet(bytes([124,133])+b'first')))
        result=decoder.feed(self.packet(bytes([124,69])+b'last',True))
        self.assertEqual(result,(123,b'\x00\x00\x00\x01\x65firstlast'))
    def test_new_timestamp_discards_incomplete_old_frame(self):
        decoder=H264RTP()
        decoder.feed(self.packet(bytes([124,133])+b'old'))
        result=decoder.feed(self.packet(b'\x65new',True,456))
        self.assertEqual(result,(456,b'\x00\x00\x00\x01\x65new'))
    def test_bad_packets_do_not_get_assigned_a_timestamp(self):
        for packet in (b'',b'bad',bytes(12)):
            with self.assertRaises(ValueError):rtp_payload(packet)


class GatewayTests(unittest.TestCase):
    def test_leases_are_bound_to_cookie_hash(self):
        gateway=MediaGateway()
        request=SimpleNamespace(cookies={'safety_session':'private-session'})
        gateway.leases['owned']={'owner':gateway.cookie_hash(request)}
        self.assertIs(gateway.owned('owned',request),gateway.leases['owned'])
        with self.assertRaises(HTTPException):gateway.owned('owned',SimpleNamespace(cookies={}))
    def test_disabled_and_unknown_paths_fail_closed(self):
        gateway=MediaGateway();gateway.enabled=False
        with self.assertRaises(HTTPException):gateway.path('CAM-01')
        gateway.enabled=True
        with self.assertRaises(HTTPException):gateway.path('../../admin')


class GatewayAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoked_viewer_delete_retries_after_control_failure(self):
        gateway=MediaGateway()
        request=SimpleNamespace(cookies={'safety_session':'session'})
        gateway.leases['lease']={'owner':gateway.cookie_hash(request),'url':'http://media.invalid/cam01/whep/id','expires':100}
        client=AsyncMock()
        client.delete.side_effect=[httpx.ConnectError('offline'),httpx.Response(204)]
        context=AsyncMock();context.__aenter__.return_value=client
        with patch.dict(os.environ,{'MEDIA_WEB_PASSWORD':'test-only'}),patch('media_gateway.httpx.AsyncClient',return_value=context):
            await gateway.delete('lease')
            self.assertTrue(gateway.leases['lease']['revoked'])
            with self.assertRaises(HTTPException):gateway.owned('lease',request)
            await gateway.delete('lease')
            self.assertNotIn('lease',gateway.leases)

    async def test_upstream_session_location_cannot_escape_camera_path(self):
        gateway=MediaGateway();gateway.enabled=True
        client=AsyncMock();context=AsyncMock();context.__aenter__.return_value=client
        for location in ('/admin','/cam02/whep/id','/cam01/whep/../admin'):
            client.post.return_value=httpx.Response(201,headers={'location':location},content=b'sdp')
            with patch.dict(os.environ,{'MEDIA_WEB_PASSWORD':'test-only'}),patch('media_gateway.httpx.AsyncClient',return_value=context):
                with self.assertRaises(HTTPException):
                    await gateway.offer('CAM-01',b'offer',SimpleNamespace(cookies={}))
            self.assertFalse(gateway.leases)
