import tempfile
import unittest
from pathlib import Path

import launcher


class OpenLogTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.log = Path(self.folder.name) / "app.log"

    def write(self, text, limit=100):
        with launcher.open_log(self.log, limit) as f:
            f.write(text)

    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_a_new_start_adds_to_the_old_log(self):
        self.write("crash ")
        self.write("second run")
        self.assertEqual(self.read(self.log), "crash second run")

    def test_a_log_over_the_limit_moves_to_dot_1_and_starts_fresh(self):
        self.write("a" * 101)
        self.write("new")
        self.assertEqual(self.read(self.log), "new")
        self.assertEqual(self.read(self.log.with_name("app.log.1")), "a" * 101)

    def test_only_one_old_log_is_kept(self):
        self.write("a" * 101)
        self.write("b" * 101)
        self.write("c")
        self.assertEqual(self.read(self.log.with_name("app.log.1")), "b" * 101)
        self.assertEqual(self.read(self.log), "c")

    def test_a_log_exactly_at_the_limit_stays(self):
        self.write("a" * 100)
        self.write("b")
        self.assertFalse(self.log.with_name("app.log.1").exists())


if __name__ == "__main__":
    unittest.main()
