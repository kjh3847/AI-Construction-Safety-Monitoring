"""Record explicit negative model classes, not inferred worker violations."""
import os
from database import save_event
from person_safety import event_counts, associate_people
from person_tracker import PersonTracker

NEGATIVE_CLASSES = {'NO-Hardhat', 'NO-Safety Vest'}
WARNING_INTERVAL_SECONDS = 600
# Brief model dropouts do not imply that a worker put their equipment on.
CONTINUITY_GAP_SECONDS = 2


class EventRecorder:
    def __init__(self, source_id, model_name, source_name, camera_name='CAM-01', lost_seconds=None):
        self.source_id = source_id
        self.model_name = model_name
        self.source_name = source_name
        self.tracker = PersonTracker(float(os.getenv('EVENT_TRACK_LOST_SECONDS', '10')) if lost_seconds is None else lost_seconds)
        self.camera_name = camera_name
        self.episode_keys = []

    def record(self, detections, frame_number, video_seconds, detected_at=None):
        self.episode_keys = []
        tracks = self.tracker.update(detections, frame_number, video_seconds)
        association = associate_people(detections)
        saved = []
        for person in association['person_safety']:
            track = tracks.get(person['detection_index'])
            if not person['violations'] or track is None:
                continue
            if ('last_negative' not in track or
                    video_seconds - track['last_negative'] > CONTINUITY_GAP_SECONDS):
                track.update(negative_since=video_seconds, negative_start_frame=frame_number,
                             warning_bucket=0)
            track['last_negative'] = video_seconds
            duration = max(0, video_seconds - track['negative_since'])
            bucket = int(duration // WARNING_INTERVAL_SECONDS)
            is_warning = track['recorded'] and bucket > track['warning_bucket']
            if track['recorded'] and not is_warning:
                continue
            # Only explicit negative boxes unambiguously linked to this person.
            evidence = [detections[i] for i in person['evidence_indices']]
            strongest = max(evidence, key=lambda d: d['confidence'])
            key = f"{self.source_id}:{self.camera_name}:person-v1:{track['id']}"
            if is_warning:
                key += f":sustained:{track['negative_start_frame']}:{bucket}"
            counts = event_counts(detections, strongest['class_name'])
            counts['event_person_count'] = 1
            event_id = save_event(
                camera_name=self.camera_name, event_type=strongest['class_name'],
                model_name=self.model_name, confidence=strongest['confidence'],
                source_name=self.source_name, video_seconds=video_seconds, event_key=key,
                detected_at=detected_at, counts=counts, person_track_id=track['id'],
                violation_types=person['violations'],
                event_reason='sustained' if is_warning else 'initial',
                sustained_seconds=duration, repeat_index=bucket if is_warning else 0,
            )
            track['recorded'] = True
            track['warning_bucket'] = bucket
            # Replays may reattach evidence, but never insert another DB row.
            self.episode_keys.append(key)
            if event_id is not None:
                saved.append(event_id)
        return saved
