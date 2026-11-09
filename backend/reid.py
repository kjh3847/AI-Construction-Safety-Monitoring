"""Anonymous tracklet association; no faces, names, or fallback fake embeddings."""
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
import time
import uuid

import cv2
import numpy as np

from database import get_connection


class OSNetEncoder:
    """An explicitly supplied, trained OSNet ONNX export (RGB/ImageNet, 256x128)."""
    def __init__(self, path=None):
        self.path = path or os.getenv('REID_MODEL_PATH', '')
        self.session = None
        self.lock = RLock()
        self.fingerprint = None
        self.state = 'disabled' if not self.path else 'pending'

    def encode(self, frame, people):
        if not self.path or self.state == 'unavailable':
            return [None] * len(people)
        try:
            with self.lock:
                if self.session is None:
                    import onnxruntime as ort
                    path = Path(self.path)
                    self.fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
                    options = ort.SessionOptions()
                    options.intra_op_num_threads = max(1,int(os.getenv('REID_THREADS','1')))
                    options.inter_op_num_threads = 1
                    self.session = ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
                    self.state = 'ready'
                vectors = []
                for person in people:
                    x1, y1, x2, y2 = map(int, person['bbox'])
                    height, width = frame.shape[:2]
                    crop = frame[max(0,y1):min(height,y2), max(0,x1):min(width,x2)]
                    area = max(1,(x2-x1)*(y2-y1))
                    occluded = False
                    for other in people:
                        if other is person:
                            continue
                        a,b,c,d = other['bbox']
                        overlap = max(0,min(x2,c)-max(x1,a))*max(0,min(y2,d)-max(y1,b))
                        if overlap/area > .3:
                            occluded = True
                    if (crop.size == 0 or crop.shape[0] < 64 or crop.shape[1] < 24
                            or occluded
                            or person['confidence'] < .6
                            or cv2.Laplacian(crop, cv2.CV_64F).var() < 20):
                        vectors.append(None)
                        continue
                    rgb = cv2.cvtColor(cv2.resize(crop, (128,256)), cv2.COLOR_BGR2RGB).astype(np.float32)/255
                    tensor = ((rgb - np.array([.485,.456,.406], np.float32)) /
                              np.array([.229,.224,.225], np.float32)).transpose(2,0,1)[None]
                    raw = self.session.run(None, {self.session.get_inputs()[0].name: tensor})[0].reshape(-1)
                    norm = np.linalg.norm(raw)
                    vectors.append(raw/norm if norm > 0 and np.isfinite(raw).all() else None)
                return vectors
        except Exception:
            # Fail closed for identity matching, while PPE detection continues.
            self.state = 'unavailable'
            return [None] * len(people)


def normalize(vector):
    if vector is None:
        return None
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vector)
    return vector/norm if norm > 0 and np.isfinite(vector).all() else None


class GlobalTracker:
    def __init__(self, encoder=None, transitions=None, threshold=None, margin=.08, ttl=300):
        self.encoder = encoder or OSNetEncoder()
        self.transitions = json.loads(os.getenv('REID_TRANSITIONS', '{}')) if transitions is None else transitions
        for key, window in self.transitions.items():
            if ('>' not in key or len(window) != 2 or not 0 <= window[0] < window[1] <= ttl):
                raise ValueError('Invalid REID_TRANSITIONS travel window')
        self.threshold = float(os.getenv('REID_THRESHOLD', '.88')) if threshold is None else threshold
        self.margin, self.ttl = margin, ttl
        self.lock = RLock()
        self.tracklets = {}

    def initialize(self):
        with self.lock, get_connection() as conn:
            self.tracklets = {row['id']: dict(row) for row in conn.execute(
                'SELECT * FROM person_tracklets WHERE last_seen >= ?', (time.time()-self.ttl,))}

    def observe(self, camera_id, session_id, people, timestamp, vectors=None, violations=None):
        vectors = vectors if vectors is not None else [None] * len(people)
        violations = violations or {}
        output = {}
        with self.lock, get_connection() as conn:
            self.tracklets = {key: row for key, row in self.tracklets.items()
                              if timestamp-row['last_seen'] <= self.ttl}
            for person, vector in zip(people, vectors):
                local_id = str(person['track_id'])
                key = f'{camera_id}:{session_id}:{local_id}'
                vector = normalize(vector)
                row = self.tracklets.get(key)
                if row is None:
                    retained = conn.execute('SELECT * FROM person_tracklets WHERE id=?',(key,)).fetchone()
                    if retained:
                        row = dict(retained)
                        self.tracklets[key] = row
                if row is None:
                    candidates = {}
                    for old in self.tracklets.values():
                        edge = self.transitions.get(f"{old['camera_id']}>{camera_id}")
                        if old['camera_id'] == camera_id:
                            edge = [2, min(60,self.ttl)]
                        elapsed = timestamp-old['last_seen']
                        if (vector is None or edge is None or not max(2,edge[0]) <= elapsed <= edge[1]
                                or not old['embedding'] or old['model_fingerprint'] != self.encoder.fingerprint):
                            continue
                        # Never assign the same identity to simultaneous local tracks,
                        # including two people entering this camera in the same batch.
                        if any(other['global_person_id'] == old['global_person_id']
                               and timestamp-other['last_seen'] < 2 for other in self.tracklets.values()):
                            continue
                        prior = np.asarray(json.loads(old['embedding']), dtype=np.float32)
                        if prior.shape != vector.shape:
                            continue
                        score = float(np.dot(vector, prior))
                        gid = old['global_person_id']
                        candidates[gid] = max(score, candidates.get(gid, -1))
                    ranked = sorted(((score,gid) for gid,score in candidates.items()), reverse=True)
                    accepted = ranked and ranked[0][0] >= self.threshold and (
                        len(ranked) == 1 or ranked[0][0]-ranked[1][0] >= self.margin)
                    gid = ranked[0][1] if accepted else 'P' + uuid.uuid4().hex[:16].upper()
                    state = 'estimated' if accepted else 'unconfirmed'
                    reason = ('appearance_and_travel_window' if accepted else
                              'ambiguous_candidates' if ranked else 'no_eligible_candidate')
                    conn.execute('INSERT OR IGNORE INTO global_people VALUES (?,?)', (gid,timestamp))
                    row = dict(id=key, global_person_id=gid, camera_id=camera_id, local_track_id=local_id,
                        first_seen=timestamp, last_seen=timestamp, embedding=None,
                        similarity=ranked[0][0] if ranked else None, match_state=state, reason=reason,
                        violations='[]', model_fingerprint=self.encoder.fingerprint)
                    self.tracklets[key] = row
                row['last_seen'] = timestamp
                row['violations'] = json.dumps(violations.get(local_id, []))
                if vector is not None:
                    row['embedding'] = json.dumps(vector.tolist())
                    row['model_fingerprint'] = self.encoder.fingerprint
                conn.execute('''INSERT INTO person_tracklets VALUES
                    (:id,:global_person_id,:camera_id,:local_track_id,:first_seen,:last_seen,
                     :embedding,:similarity,:match_state,:reason,:violations,:model_fingerprint)
                    ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,
                    embedding=excluded.embedding, violations=excluded.violations,
                    model_fingerprint=excluded.model_fingerprint''', row)
                output[local_id] = {name: row[name] for name in
                    ('global_person_id','similarity','match_state','reason','first_seen','last_seen')}
                output[local_id]['tracklet_id'] = key
        return output

    def history(self, global_id=None, limit=100):
        with get_connection() as conn:
            rows = conn.execute('''SELECT id,global_person_id,camera_id,local_track_id,first_seen,last_seen,
                similarity,match_state,reason,violations FROM person_tracklets ''' +
                ('WHERE global_person_id=? ' if global_id else '') + 'ORDER BY last_seen DESC LIMIT ?',
                (global_id,limit) if global_id else (limit,)).fetchall()
            return [dict(row) for row in rows]

    def correct(self, tracklet_id, target, actor, reason):
        with self.lock, get_connection() as conn:
            row = conn.execute('SELECT * FROM person_tracklets WHERE id=?', (tracklet_id,)).fetchone()
            if row is None:
                raise KeyError('Tracklet not found')
            target = target or 'P' + uuid.uuid4().hex[:16].upper()
            if target != row['global_person_id']:
                # A merge is explicit; a blank target splits only this tracklet.
                if conn.execute('SELECT 1 FROM global_people WHERE id=?', (target,)).fetchone() is None:
                    conn.execute('INSERT INTO global_people VALUES (?,?)', (target,time.time()))
            conn.execute('INSERT INTO identity_corrections(tracklet_id,old_id,new_id,actor,reason,corrected_at) VALUES (?,?,?,?,?,?)',
                (tracklet_id,row['global_person_id'],target,actor,reason,time.time()))
            conn.execute("UPDATE person_tracklets SET global_person_id=?,match_state='manual',reason=? WHERE id=?",
                         (target,reason,tracklet_id))
            conn.execute("UPDATE safety_events SET global_person_id=?,match_state='manual',notification_suppressed=0 WHERE tracklet_id=?", (target,tracklet_id))
            if tracklet_id in self.tracklets:
                self.tracklets[tracklet_id].update(global_person_id=target, match_state='manual', reason=reason)
            return {'tracklet_id':tracklet_id, 'global_person_id':target, 'match_state':'manual'}
