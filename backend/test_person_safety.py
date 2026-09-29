import unittest
from person_safety import associate_people
from monitor import frame_payload


def detection(name, bbox):
    return {'class_name': name, 'bbox': bbox, 'confidence': .9}


class PersonSafetyTest(unittest.TestCase):
    def test_multiple_missing_items_count_one_person(self):
        result = associate_people([detection('Person',[0,0,100,200]),
            detection('NO-Hardhat',[30,0,70,40]), detection('NO-Safety Vest',[20,60,80,150]),
            detection('NO-Safety Vest',[25,70,75,140])])
        self.assertEqual(result['noncompliant_person_count'],1)
        self.assertEqual(result['unassigned_negative_count'],0)
        self.assertEqual(len(result['person_safety'][0]['violations']),2)

    def test_two_people_and_next_empty_frame(self):
        result = associate_people([detection('Person',[0,0,100,200]),detection('Person',[200,0,300,200]),
            detection('NO-Hardhat',[30,0,70,40]),detection('NO-Safety Vest',[220,60,280,150])])
        self.assertEqual(result['noncompliant_person_count'],2)
        self.assertEqual(associate_people([])['noncompliant_person_count'],0)

    def test_ambiguous_and_unmatched_not_invented_people(self):
        negative = detection('NO-Hardhat',[30,0,70,40])
        result = associate_people([detection('Person',[0,0,100,200]),detection('Person',[5,0,105,200]),negative])
        self.assertEqual(result['noncompliant_person_count'],0)
        self.assertEqual(result['unassigned_negative_count'],1)
        self.assertEqual(associate_people([negative])['unassigned_negative_count'],1)
        self.assertEqual(associate_people([negative])['noncompliant_person_count'],0)

    def test_body_region_and_positive_classes(self):
        result = associate_people([detection('Person',[0,0,100,200]),
            detection('NO-Hardhat',[30,150,70,190]),detection('Hardhat',[30,0,70,40])])
        self.assertEqual(result['noncompliant_person_count'],0)
        self.assertEqual(result['unassigned_negative_count'],1)

    def test_legacy_frame_uses_own_boxes(self):
        meta = {'detections':[detection('Person',[0,0,100,200]),detection('NO-Hardhat',[30,0,70,40])],
                'noncompliant_person_count':None}
        result = frame_payload((meta,b'jpeg'))
        self.assertEqual(result['noncompliant_person_count'],1)
        self.assertIsNone(meta['noncompliant_person_count'])
        self.assertIsNone(associate_people([{'class_name':'Person'}])['noncompliant_person_count'])


if __name__ == '__main__':
    unittest.main()
