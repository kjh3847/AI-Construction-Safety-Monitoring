import tempfile
import unittest
from pathlib import Path
import database


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = database.DB_PATH
        database.DB_PATH = Path(self.temp.name) / 'test.db'

    def tearDown(self):
        database.DB_PATH = self.original
        self.temp.cleanup()

    def test_new_database_supports_event_review(self):
        database.init_db()
        event_id = database.save_event('CAM-01', 'NO-Hardhat')
        self.assertEqual(database.event_summary()['pending'], 1)
        database.review_event(event_id)
        self.assertEqual(database.event_summary()['pending'], 0)

    def test_repairs_missing_comma_schema_without_losing_events(self):
        with database.get_connection() as conn:
            conn.execute("""CREATE TABLE safety_events (
                id INTEGER PRIMARY KEY, camera_name TEXT, event_type TEXT,
                track_id INTEGER review_status TEXT NOT NULL DEFAULT 'pending')""")
            conn.execute("INSERT INTO safety_events (id,camera_name,event_type) VALUES (1,'CAM-01','NO-Hardhat')")
        database.init_db()
        database.init_db()
        self.assertEqual(database.event_summary(), {'total': 1, 'pending': 1})


if __name__ == '__main__':
    unittest.main()
