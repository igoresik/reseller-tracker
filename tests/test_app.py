import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

import db

APP = str(Path(db.__file__).with_name("app.py"))


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        patcher = patch.object(db, "DB_PATH", Path(self.folder.name) / "tracker.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)
        st.cache_resource.clear()

    def test_database_setup_runs_once_not_on_every_click(self):
        with patch.object(db, "init", wraps=db.init) as init:
            app = AppTest.from_file(APP, default_timeout=30).run()
            app.run()
        self.assertEqual(app.exception, [])
        self.assertEqual(init.call_count, 1)


if __name__ == "__main__":
    unittest.main()
