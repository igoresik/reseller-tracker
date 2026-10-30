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

    def test_fee_percent_cannot_go_over_100(self):
        with patch.object(st, "data_editor", wraps=st.data_editor) as editor:
            AppTest.from_file(APP, default_timeout=30).run()
        column = editor.call_args.kwargs["column_config"]["fee_pct"]
        self.assertEqual(column["type_config"]["max_value"], 100.0)

    def test_parcel_heading_escapes_markdown_in_the_title(self):
        db.init()
        db.add_listing("Tee *new* $5 or $6 :red[L]", "", "", "Depop", 100, 500)
        db.mark_sold(1, 500, 0)
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertEqual(app.exception, [])
        self.assertIn(r"Tee \*new\* \$5 or \$6 \:red\[L\]", [h.value for h in app.subheader])


if __name__ == "__main__":
    unittest.main()
