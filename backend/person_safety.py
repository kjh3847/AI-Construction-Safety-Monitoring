"""Frame-local, conservative spatial association; counts are estimates, not identities."""
import math

ASSOCIATION_METHOD = 'spatial-v1'
NEGATIVE_CLASSES = {'NO-Hardhat', 'NO-Safety Vest'}
POSITIVE_CLASSES = {'Hardhat': 'NO-Hardhat', 'Safety Vest': 'NO-Safety Vest'}


def event_counts(detections, event_type):
    association = associate_people(detections)
    available = association['noncompliant_person_count'] is not None
    return {
        'person_count': sum(d['class_name'] == 'Person' for d in detections) if available else None,
        'noncompliant_person_count': association['noncompliant_person_count'],
        'event_person_count': sum(event_type in person['violations'] for person in association['person_safety']) if available else None,
        'unassigned_negative_count': association['unassigned_negative_count'],
        'association_method': association['person_association_method'],
    }


def _box(detection):
    box = detection.get('bbox')
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
        return None
    return box if box[2] > box[0] and box[3] > box[1] else None


def associate_people(detections):
    relevant = [(i, d) for i, d in enumerate(detections)
                if d['class_name'] in NEGATIVE_CLASSES | {'Person'}]
    if any(_box(d) is None for _, d in relevant):
        return {'noncompliant_person_count': None, 'unassigned_negative_count': None,
                'person_association_method': 'unavailable', 'person_safety': []}
    people = [(i, d['bbox']) for i, d in relevant if d['class_name'] == 'Person']
    violations = {i: set() for i, _ in people}
    worn = {i: set() for i, _ in people}
    evidence = {i: [] for i, _ in people}
    unassigned = 0
    for detection_index, detection in enumerate(detections):
        name = detection['class_name']
        negative = name in NEGATIVE_CLASSES
        equipment = name if negative else POSITIVE_CLASSES.get(name)
        if equipment is None or _box(detection) is None:
            continue
        x1, y1, x2, y2 = detection['bbox']
        cx, cy = (x1+x2)/2, (y1+y2)/2
        area = (x2-x1)*(y2-y1)
        candidates = []
        for person_index, (px1, py1, px2, py2) in people:
            relative_y = (cy-py1)/(py2-py1)
            # Equipment evidence must lie on the head or torso region.
            low, high = (0, .45) if equipment == 'NO-Hardhat' else (.15, .85)
            if not (px1 <= cx <= px2 and low <= relative_y <= high):
                continue
            intersection = max(0, min(x2,px2)-max(x1,px1)) * max(0,min(y2,py2)-max(y1,py1))
            coverage = intersection/area
            if coverage < .6:
                continue
            center_distance = abs(cx-(px1+px2)/2)/(px2-px1)
            candidates.append((coverage - .25*center_distance, person_index))
        candidates.sort(reverse=True)
        # Crowded/overlapping people: do not force a near-tie to either person.
        if not candidates or (len(candidates)>1 and candidates[0][0]-candidates[1][0] < .15):
            unassigned += int(negative)
        elif negative:
            violations[candidates[0][1]].add(name)
            evidence[candidates[0][1]].append(detection_index)
        else:
            worn[candidates[0][1]].add(equipment)
    return {
        'noncompliant_person_count': sum(bool(names) for names in violations.values()),
        'unassigned_negative_count': unassigned,
        'person_association_method': ASSOCIATION_METHOD,
        'person_safety': [{'detection_index': i, 'violations': sorted(names), 'worn': sorted(worn[i]),
                           'evidence_indices': evidence[i]} for i, names in violations.items()],
    }
