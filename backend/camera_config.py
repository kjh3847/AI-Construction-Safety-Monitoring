"""Private input configuration. Public status never contains source addresses."""
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def classify_source(value):
    if value is None or str(value).strip() == '':
        return None, 'unconfigured'
    value = str(value).strip()
    if value.isdecimal():
        return int(value), 'usb'
    scheme = urlsplit(value).scheme.lower()
    if scheme in ('http', 'https', 'rtsp', 'rtsps'):
        return value, scheme
    if '://' in value:
        raise ValueError('Unsupported camera protocol')
    return value, 'file'


def camera_configs(base):
    configs, seen, names = [], {}, set()
    for number in range(1, 4):
        camera_id = f'CAM-{number:02}'
        source = os.getenv(f'CAMERA_{number:02}_SOURCE', '').strip()
        relay = os.getenv('MEDIA_ENABLED','false').lower()=='true' and os.getenv(f'CAMERA_{number:02}_INPUT','push')=='push'
        if relay:
            from urllib.parse import quote
            password=os.getenv('MEDIA_AI_PASSWORD','')
            if not password:raise ValueError('MEDIA_AI_PASSWORD is required for MediaMTX input')
            endpoint=os.getenv('MEDIA_RTSP_URL','rtsp://mediamtx:8554').rstrip('/')
            parts=urlsplit(endpoint)
            source=urlunsplit((parts.scheme,quote(os.getenv('MEDIA_AI_USER','ai_reader'),safe='')+':'+quote(password,safe='')+'@'+parts.netloc,
                              parts.path+f'/cam{number:02}','',''))
        if not source and number == 1:
            source = os.getenv('CAMERA_SOURCE', '').strip()
        # Keep the legacy local demo when its file actually exists.
        demo = Path(base) / ('test.mp4' if number == 1 else f'test{number}.mp4')
        if not source and demo.is_file():
            source = str(demo)
        _, kind = classify_source(source)
        name = os.getenv(f'CAMERA_{number:02}_NAME', camera_id).strip() or camera_id
        if name in names:
            raise ValueError('Camera display names must be unique for event routing')
        names.add(name)
        duplicate = False
        if source:
            # Credentials do not make the same video endpoint independent.
            if kind in ('http', 'https', 'rtsp', 'rtsps'):
                parts = urlsplit(source)
                canonical = urlunsplit((parts.scheme.lower(), parts.netloc.rsplit('@', 1)[-1].lower(),
                                       parts.path.rstrip('/'), parts.query, ''))
            else:
                canonical = source
            duplicate = canonical in seen
            if duplicate:
                logging.getLogger(__name__).warning('Duplicate source configured for %s and %s', seen[canonical], camera_id)
            seen[canonical] = camera_id
        configs.append(dict(camera_id=camera_id, name=name, source=source, duplicate_source=duplicate,
                            adapter='mediamtx' if relay else 'direct'))
    return configs
