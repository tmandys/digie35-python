"""Run: python -m unittest discover -s tests -p test_mjpgserver.py"""
import importlib.util
import io
import tempfile
import threading
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "mjpg_under_test", Path(__file__).resolve().parents[1] / "digie35/mjpgserver.py")
mjpg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mjpg)


def handler(path, buffer=None):
    result = object.__new__(mjpg.StreamingHandler)
    result.path = path
    result.frames_buffer = buffer or mjpg.FrameBuffer()
    result.snapshot_list = mjpg.RingBuffer()
    result.wfile = io.BytesIO()
    result.client_address = ("test", 0)
    result.responses = []
    result.send_response = lambda code: result.responses.append(code)
    result.send_error = lambda code, *args: result.responses.append(code)
    result.send_header = lambda *args: None
    result.end_headers = lambda: None
    return result


class MjpgTests(unittest.TestCase):
    def test_archive_paths_and_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "photos"
            folder = base / ".previews/p/f"
            folder.mkdir(parents=True)
            mjpg.set_base_dir(base)
            self.addCleanup(mjpg.set_base_dir, None)
            (Path(tmp) / "photos-secret.preview.jpg").write_bytes(b"outside")
            (base / "secret.preview.jpg").write_bytes(b"outside previews")
            (folder / "image.preview.jpg").write_bytes(b"image")
            (folder / "image.preview.json").write_text("{broken")
            for path in ["/preview/archive/../../photos-secret", "/preview/archive/.././secret"]:
                h = handler(path)
                h.do_GET()
                self.assertEqual(h.responses, [404])
                self.assertEqual(h.wfile.getvalue(), b"")
            h = handler("/preview/archive/p/f/image")
            h.do_GET()
            self.assertEqual(h.responses, [200])
            self.assertEqual(h.wfile.getvalue(), b"image")
            h = handler("/preview/archive/p/f/image?info=1")
            h.do_GET()
            self.assertEqual(h.responses, [500])

    def test_slow_client_does_not_block_producer_or_other_client(self):
        buffer = mjpg.FrameBuffer()
        buffer.write(memoryview(b"\xff\xd8first"))
        blocked = threading.Event()
        release = threading.Event()
        produced = threading.Event()
        received = threading.Event()
        class SlowOutput:
            def write(self, data):
                blocked.set()
                release.wait(5)
        class FastOutput:
            def write(self, data):
                if data == b"\xff\xd8second":
                    received.set()
        slow = handler("/stream", buffer)
        slow.wfile = SlowOutput()
        fast = handler("/stream", buffer)
        fast.wfile = FastOutput()
        threads = []
        def start(callback):
            thread = threading.Thread(target=callback, daemon=True)
            threads.append(thread)
            thread.start()
        try:
            start(slow.do_GET)
            self.assertTrue(blocked.wait(1))
            def produce():
                buffer.write(memoryview(b"\xff\xd8second"))
                produced.set()
            start(produce)
            self.assertTrue(produced.wait(1), "Producer blocked on client output")
            start(fast.do_GET)
            self.assertTrue(received.wait(1), "Second client did not receive frame")
        finally:
            release.set()
            buffer.stop()
            for thread in threads:
                thread.join(2)
        self.assertTrue(all(not thread.is_alive() for thread in threads))

    def test_stop_wakes_client_waiting_for_first_frame(self):
        buffer = mjpg.FrameBuffer()
        waiting = threading.Event()
        original_wait = buffer.condition.wait
        def wait(*args, **kwargs):
            waiting.set()
            return original_wait(*args, **kwargs)
        buffer.condition.wait = wait
        h = handler("/stream", buffer)
        thread = threading.Thread(target=h.do_GET, daemon=True)
        thread.start()
        try:
            self.assertTrue(waiting.wait(1))
        finally:
            buffer.stop()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(h.wfile.getvalue(), b"")


if __name__ == "__main__":
    unittest.main()
