import unittest
from live_capture import LatestFrameReader


class FakeCamera:
    def __init__(self):
        self.frames = iter(range(100))
        self.released = False

    def read(self):
        value = next(self.frames, None)
        return value is not None, value

    def release(self):
        self.released = True


class LatestFrameTests(unittest.TestCase):
    def test_slow_consumer_gets_latest_not_backlog(self):
        camera = FakeCamera()
        reader = LatestFrameReader(camera)
        reader.thread.join(timeout=2)
        ok, frame, captured = reader.read()
        self.assertTrue(ok)
        self.assertEqual(frame, 99)
        self.assertGreater(captured, 0)
        self.assertEqual(reader.read(), (False, None, None))
        reader.close()
        self.assertTrue(camera.released)


if __name__ == '__main__':
    unittest.main()
