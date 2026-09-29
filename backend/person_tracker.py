"""Camera-local spatial tracks; these are not biometric person identities."""
from person_safety import _box


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return intersection / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection)


def framing_change(a, b):
    # A near-instant zoom can have low IoU even though much of the smaller
    # person box remains inside the enlarged box. Restrict to modest shifts.
    areas = [(box[2]-box[0])*(box[3]-box[1]) for box in (a,b)]
    intersection = max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
    dx = abs(a[0]+a[2]-b[0]-b[2]) / (a[2]-a[0]+b[2]-b[0])
    dy = abs(a[1]+a[3]-b[1]-b[3]) / (a[3]-a[1]+b[3]-b[1])
    return max(areas)/min(areas) <= 4 and intersection/min(areas) >= .45 and dx <= .75 and dy <= .5


class PersonTracker:
    def __init__(self, lost_seconds=10):
        self.lost_seconds = lost_seconds
        self.tracks = {}

    def update(self, detections, frame_number, seconds):
        self.tracks = {key: track for key, track in self.tracks.items()
                       if 0 <= seconds-track['seen'] <= self.lost_seconds}
        people = {i: _box(d) for i, d in enumerate(detections)
                  if d['class_name'] == 'Person' and _box(d) is not None}
        candidates = []
        for key, track in self.tracks.items():
            elapsed = min(max(seconds-track['seen'], 0), .5)
            predicted = [v+speed*elapsed for v, speed in zip(track['box'], track['velocity'])]
            if _box({'bbox': predicted}) is None:
                predicted = track['box']
            for index, box in people.items():
                score = max(iou(box, predicted), iou(box, track['box']))
                if seconds-track['seen'] <= .5 and framing_change(box, track['box']):
                    score = max(score, .25)
                if score >= .25:
                    candidates.append((score, key, index))
        matches, used = {}, set()
        for _, key, index in sorted(candidates, reverse=True):
            if key not in used and index not in matches:
                matches[index] = key
                used.add(key)
        result = {}
        for index, box in people.items():
            key = matches.get(index)
            if key is None:
                key = f'{frame_number}-{index}'
                track = {'recorded': False, 'velocity': [0]*4}
                self.tracks[key] = track
            else:
                track = self.tracks[key]
                elapsed = seconds-track['seen']
                if elapsed > 0:
                    track['velocity'] = [(v-old)/elapsed for v, old in zip(box, track['box'])]
            track.update(box=list(box), seen=seconds, id=key)
            detections[index]['track_id'] = key
            result[index] = track
        return result
