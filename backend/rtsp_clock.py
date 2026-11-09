"""H.264 RTSP/TCP adapter preserving source RTP timestamps for exact WebRTC overlays.

Used only for the private MediaMTX adapter. Legacy RTSP/HTTP/USB retain OpenCV.
Low-delay H.264 without B-frames is the supported publisher contract.
"""
import base64
from collections import deque
from fractions import Fraction
import re
import socket
import struct
import time
from urllib.parse import unquote,urlsplit,urlunsplit,urljoin


def rtp_payload(packet):
    if len(packet)<12 or packet[0]>>6!=2:raise ValueError('Invalid RTP packet')
    offset=12+4*(packet[0]&15)
    if packet[0]&16:
        if len(packet)<offset+4:raise ValueError('Invalid RTP extension')
        offset+=4+4*struct.unpack('!H',packet[offset+2:offset+4])[0]
    end=len(packet)-(packet[-1] if packet[0]&32 else 0)
    if offset>end:raise ValueError('Invalid RTP payload')
    return struct.unpack('!I',packet[4:8])[0],bool(packet[1]&128),packet[offset:end]


class H264RTP:
    def __init__(self):
        self.timestamp=None;self.parts=[];self.fragment=None;self.size=0

    def feed(self,packet):
        timestamp,marker,payload=rtp_payload(packet)
        if timestamp!=self.timestamp:
            self.timestamp=timestamp;self.parts=[];self.fragment=None;self.size=0
        if not payload:return None
        kind=payload[0]&31
        if 1<=kind<=23:self.parts.append(payload)
        elif kind==24:
            offset=1
            while offset+2<=len(payload):
                size=struct.unpack('!H',payload[offset:offset+2])[0];offset+=2
                if size==0 or offset+size>len(payload):raise ValueError('Invalid H264 aggregation')
                self.parts.append(payload[offset:offset+size]);offset+=size
        elif kind==28 and len(payload)>2:
            if payload[1]&128:self.fragment=bytearray([(payload[0]&224)|(payload[1]&31)])
            if self.fragment is not None:
                self.fragment.extend(payload[2:])
                if len(self.fragment)>4*1024*1024:raise ValueError('H264 frame too large')
                if payload[1]&64:self.parts.append(bytes(self.fragment));self.fragment=None
        self.size+=len(payload)
        if self.size>8*1024*1024:raise ValueError('H264 frame too large')
        if marker:
            data=b''.join(b'\x00\x00\x00\x01'+part for part in self.parts)
            self.parts=[];self.size=0
            return timestamp,data
        return None


class RTSPClockCapture:
    def __init__(self,source):
        import av
        self.av=av;self.sock=None;self.buffer=bytearray();self.frames=deque();self.sequence=0
        self.session=None;self.last_clock={};self.last_raw=None;self.unwrapped=0
        self.depacketizer=H264RTP();self.opened=False
        parts=urlsplit(source)
        if parts.scheme!='rtsp':raise ValueError('Private MediaMTX adapter requires RTSP/TCP')
        self.url=urlunsplit((parts.scheme,parts.netloc.rsplit('@',1)[-1],parts.path,parts.query,''))
        self.authorization='Basic '+base64.b64encode((unquote(parts.username or '')+':'+unquote(parts.password or '')).encode()).decode()
        try:
            self.sock=socket.create_connection((parts.hostname,parts.port or 554),timeout=5)
            self.sock.settimeout(5)
            headers,sdp=self._request('DESCRIBE',self.url,{'Accept':'application/sdp'})
            video=sdp.decode().split('m=video',1)[1].split('\nm=',1)[0]
            if not re.search(r'H264/90000',video,re.I):raise ValueError('Publisher must use H264')
            control=re.search(r'a=control:([^\r\n]+)',video)
            if control is None:raise ValueError('Missing RTSP video control')
            base=headers.get('content-base',self.url+'/')
            track=urljoin(base,control.group(1))
            setup,_=self._request('SETUP',track,{'Transport':'RTP/AVP/TCP;unicast;interleaved=0-1'})
            self.session=setup.get('session','').split(';')[0]
            if not self.session:raise ValueError('Missing RTSP session')
            self.codec=av.CodecContext.create('h264','r');self.codec.thread_count=1
            sprop=re.search(r'sprop-parameter-sets=([^;\s]+)',video)
            if sprop:self.codec.extradata=b''.join(b'\x00\x00\x00\x01'+base64.b64decode(part) for part in sprop.group(1).split(','))
            self._request('PLAY',self.url)
            self.keepalive=time.monotonic();self.opened=True
        except Exception:
            self.release();raise

    def _take(self,count):
        while len(self.buffer)<count:
            data=self.sock.recv(65536)
            if not data:raise ConnectionError('RTSP closed')
            self.buffer.extend(data)
        data=bytes(self.buffer[:count]);del self.buffer[:count];return data

    def _message(self):
        if not self.buffer:
            data=self.sock.recv(65536)
            if not data:raise ConnectionError('RTSP closed')
            self.buffer.extend(data)
        if self.buffer[0]==36:
            header=self._take(4)
            return header[1],self._take(struct.unpack('!H',header[2:])[0])
        while b'\r\n\r\n' not in self.buffer:
            data=self.sock.recv(8192)
            if not data:raise ConnectionError('RTSP closed')
            self.buffer.extend(data)
            if len(self.buffer)>65536:raise ValueError('RTSP headers too large')
        offset=self.buffer.index(b'\r\n\r\n')+4
        lines=self._take(offset).decode('utf-8').split('\r\n')
        if not lines[0].startswith('RTSP/1.0 200'):raise ConnectionError('RTSP request denied or stream offline')
        headers={key.lower():value.strip() for key,value in (line.split(':',1) for line in lines[1:] if ':' in line)}
        length=int(headers.get('content-length','0'))
        if length>1024*1024:raise ValueError('RTSP body too large')
        return headers,self._take(length)

    def _send(self,method,url,extra=None):
        self.sequence+=1
        headers={'CSeq':str(self.sequence),'Authorization':self.authorization,**(extra or {})}
        if self.session:headers['Session']=self.session
        self.sock.sendall((f'{method} {url} RTSP/1.0\r\n'+''.join(f'{key}: {value}\r\n' for key,value in headers.items())+'\r\n').encode())

    def _request(self,method,url,extra=None):
        self._send(method,url,extra)
        while True:
            headers,body=self._message()
            if isinstance(headers,dict):return headers,body

    def isOpened(self):return self.opened
    def set(self,*args):return True

    def read(self):
        deadline=time.monotonic()+10
        while self.opened and not self.frames:
            if time.monotonic()>deadline:raise TimeoutError('No H264 frame received')
            if time.monotonic()-self.keepalive>15:
                self._send('OPTIONS',self.url);self.keepalive=time.monotonic()
            channel,data=self._message()
            if channel!=0:continue
            unit=self.depacketizer.feed(data)
            if unit is None:continue
            timestamp,payload=unit
            if not payload:continue
            if self.last_raw is None:self.unwrapped=timestamp
            else:self.unwrapped+=((timestamp-self.last_raw+2**31)%2**32)-2**31
            self.last_raw=timestamp
            packet=self.av.Packet(payload);packet.pts=self.unwrapped;packet.dts=self.unwrapped;packet.time_base=Fraction(1,90000)
            for frame in self.codec.decode(packet):
                self.frames.append((frame.to_ndarray(format='bgr24'),int(frame.pts)))
        if not self.frames:return False,None
        image,pts=self.frames.popleft()
        self.last_clock={'rtp_timestamp':pts%(2**32),'media_time':pts/90000,
                         'capture_time':None,'clock_trust':'media-only'}
        return True,image

    def release(self):
        self.opened=False
        if self.sock:
            try:self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            self.sock.close();self.sock=None
