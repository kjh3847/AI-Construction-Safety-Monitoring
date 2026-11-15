"""Bounded, resumable-in-order uploads for the single CAM-04 test source."""
from pathlib import Path
from threading import Lock
from time import monotonic

import cv2
from fastapi import HTTPException


CHUNK_BYTES = 512 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024


class TestVideoUpload:
    def __init__(self, monitor):
        self.monitor = monitor
        self.pending = Path(monitor.upload_path).with_name('.incoming.mp4')
        self.lock = Lock()
        self.session = None

    def append(self, owner, upload_id, offset, total, chunk):
        with self.lock:
            now = monotonic()
            if self.session and now - self.session['time'] > 120:
                self.session = None
                self.pending.unlink(missing_ok=True)
            if offset == 0:
                if self.session and self.session['owner'] != owner:
                    raise HTTPException(409, '다른 사용자가 CAM 4 영상을 업로드 중입니다.')
                self.session = dict(owner=owner, id=upload_id, total=total, offset=0, time=now)
            session = self.session
            if (not session or (session['owner'], session['id'], session['total'], session['offset'])
                    != (owner, upload_id, total, offset)):
                raise HTTPException(409, '업로드가 중단되었습니다. 영상 파일을 다시 선택하세요.')
            if not chunk or offset + len(chunk) > total:
                raise HTTPException(400, '영상 조각의 크기가 올바르지 않습니다.')
            try:
                with self.pending.open('ab' if offset else 'wb') as stream:
                    stream.write(chunk)
                session.update(offset=offset + len(chunk), time=now)
                if session['offset'] < total:
                    return {'received': session['offset'], 'ready': False}
                try:
                    capture = cv2.VideoCapture(str(self.pending), cv2.CAP_FFMPEG)
                    try:
                        valid, frame = capture.read()
                    finally:
                        capture.release()
                    if not valid or frame is None:
                        raise HTTPException(422, '재생할 수 있는 영상 파일을 선택하세요.')
                    if not self.monitor.install_upload(self.pending):
                        raise HTTPException(409, 'CAM 4 감지 녹화를 종료한 후 다시 업로드하세요.')
                    return {'received': total, 'ready': True}
                finally:
                    self.session = None
                    self.pending.unlink(missing_ok=True)
            except OSError as error:
                self.session = None
                raise HTTPException(507, '영상 저장 공간과 권한을 확인하세요.') from error
