"""Disk-indexed DVR: bounded Python memory even with weeks of recordings."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import sqlite3
from threading import RLock
import time

from database import DEFAULT_RETENTION_SECONDS


class FrameStore:
    def __init__(self, root, retention=DEFAULT_RETENTION_SECONDS, max_bytes=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention, self.max_bytes = retention, max_bytes
        self.lock = RLock()
        self.index = self.root/'index.sqlite3'
        self.capacity_limited = False
        self.pending_deletes = {}
        with self._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS frames (
                recording_id TEXT, frame_id INTEGER, timestamp REAL NOT NULL,
                bytes INTEGER NOT NULL, PRIMARY KEY(recording_id,frame_id))''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_frame_time ON frames(timestamp)')
            conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY)')
            conn.execute('CREATE TABLE IF NOT EXISTS pending_deletes (name TEXT PRIMARY KEY, bytes INTEGER NOT NULL)')
            self.pending_deletes = {self.root/row['name']:row['bytes'] for row in conn.execute('SELECT * FROM pending_deletes')}
            if not conn.execute("SELECT 1 FROM settings WHERE key='imported'").fetchone():
                # One-time additive migration from legacy JPEG/JSON directories.
                for path in self.root.glob('*.json'):
                    if not re.fullmatch(r'[a-f0-9]{32}_\d+\.json', path.name):
                        continue
                    try:
                        meta = json.loads(path.read_text('utf-8'))
                        size = path.with_suffix('.jpg').stat().st_size
                        conn.execute('INSERT OR IGNORE INTO frames VALUES (?,?,?,?)',
                            (meta['recording_id'],meta['frame_id'],meta['timestamp'],size))
                    except (ValueError,KeyError,OSError):
                        continue
                conn.execute("INSERT INTO settings VALUES ('imported')")
            self.bytes = (conn.execute('SELECT COALESCE(SUM(bytes),0) FROM frames').fetchone()[0]
                          + sum(self.pending_deletes.values()))
            self.count = conn.execute('SELECT COUNT(*) FROM frames').fetchone()[0]
        self.prune()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.index,timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _path(self, recording_id, frame_id):
        if not re.fullmatch('[a-f0-9]{32}',str(recording_id)) or not isinstance(frame_id,int) or frame_id < 0:
            raise ValueError('Invalid frame key')
        return self.root/f'{recording_id}_{frame_id}.jpg'

    def prune(self, now=None, reserve=0):
        with self.lock, self._connect() as conn:
            for path,size in list(self.pending_deletes.items()):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
                self.bytes -= size
                del self.pending_deletes[path]
                conn.execute('DELETE FROM pending_deletes WHERE name=?',(path.name,))
            cutoff = (time.time() if now is None else now)-self.retention
            while True:
                row = conn.execute('SELECT * FROM frames ORDER BY timestamp LIMIT 1').fetchone()
                limited = self.max_bytes is not None and self.bytes+reserve > self.max_bytes
                if row is None or (row['timestamp'] >= cutoff and not limited):
                    break
                self.capacity_limited |= limited
                path = self._path(row['recording_id'],row['frame_id'])
                for target,size in ((path,row['bytes']),(path.with_suffix('.json'),0)):
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        self.pending_deletes[target] = size
                        conn.execute('INSERT OR REPLACE INTO pending_deletes VALUES (?,?)',(target.name,size))
                    else:
                        self.bytes -= size
                conn.execute('DELETE FROM frames WHERE recording_id=? AND frame_id=?',
                             (row['recording_id'],row['frame_id']))
                self.count -= 1

    def add(self, meta, jpeg):
        with self.lock:
            self.prune(reserve=len(jpeg))
            if (self.max_bytes is not None and self.bytes+len(jpeg)>self.max_bytes) or len(self.pending_deletes)>10000:
                self.capacity_limited = True
                return False
            if shutil.disk_usage(self.root).free < len(jpeg)+1024**3:
                raise OSError('Insufficient free disk space for recording')
            path = self._path(meta['recording_id'],meta['frame_id'])
            with self._connect() as conn:
                existing = conn.execute('SELECT bytes FROM frames WHERE recording_id=? AND frame_id=?',
                                       (meta['recording_id'],meta['frame_id'])).fetchone()
                if existing:
                    return True  # Immutable evidence for an exact frame key.
                # Publish metadata atomically, then make the frame seekable.
                temporary = path.with_suffix('.jpg.tmp')
                temporary.write_bytes(jpeg)
                temporary.replace(path)
                temporary = path.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(meta),encoding='utf-8')
                temporary.replace(path.with_suffix('.json'))
                conn.execute('INSERT INTO frames VALUES (?,?,?,?)',
                    (meta['recording_id'],meta['frame_id'],meta['timestamp'],len(jpeg)))
            self.bytes += len(jpeg)
            self.count += 1
            return True

    def bounds(self):
        with self.lock, self._connect() as conn:
            # Janitor prunes separately; status requests never scan metadata/files.
            first = conn.execute('SELECT timestamp FROM frames ORDER BY timestamp LIMIT 1').fetchone()
            last = conn.execute('SELECT timestamp FROM frames ORDER BY timestamp DESC LIMIT 1').fetchone()
            return dict(start=first[0] if first else None,end=last[0] if last else None,
                retention_seconds=self.retention,frames=self.count,bytes=self.bytes,max_bytes=self.max_bytes,
                capacity_limited=self.capacity_limited)

    def get(self, at=None, recording_id=None, frame_id=None):
        with self.lock, self._connect() as conn:
            cutoff = time.time()-self.retention
            if recording_id is not None:
                row = conn.execute('SELECT * FROM frames WHERE recording_id=? AND frame_id=? AND timestamp>=?',
                                   (recording_id,frame_id,cutoff)).fetchone()
            elif at is not None:
                last = conn.execute('SELECT MAX(timestamp) FROM frames').fetchone()[0]
                if last is None or at>last:
                    return None
                row = conn.execute('SELECT * FROM frames WHERE timestamp<=? AND timestamp>=? ORDER BY timestamp DESC LIMIT 1',
                                   (at,cutoff)).fetchone()
            else:
                row = conn.execute('SELECT * FROM frames WHERE timestamp>=? ORDER BY timestamp DESC LIMIT 1',(cutoff,)).fetchone()
            if row is None:
                return None
            path = self._path(row['recording_id'],row['frame_id'])
            try:
                return json.loads(path.with_suffix('.json').read_text('utf-8')),path.read_bytes()
            except (OSError,ValueError):
                return None

    def contains(self, recording_id, frame_id):
        with self.lock, self._connect() as conn:
            return conn.execute('SELECT 1 FROM frames WHERE recording_id=? AND frame_id=? AND timestamp>=?',
                (recording_id,frame_id,time.time()-self.retention)).fetchone() is not None
