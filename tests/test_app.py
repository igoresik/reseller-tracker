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

    def test_offer_starts_at_the_new_price_after_an_edit(self):
        db.init()
        db.add_listing("Jeans", "", "", "Depop", 1000, 2000)
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.number_input(key="edit_1_price").set_value(30.0)
        next(b for b in app.button if b.label == "Save changes").click().run()
        self.assertEqual(app.exception, [])
        offer = next(n for n in app.number_input if n.label == "Buyer's offer (€)")
        self.assertEqual(offer.value, 30.0)

    def test_parcel_heading_escapes_markdown_in_the_title(self):
        db.init()
        db.add_listing("Tee *new* $5 or $6 :red[L]", "", "", "Depop", 100, 500)
        db.mark_sold(1, 500, 0)
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertEqual(app.exception, [])
        self.assertIn(r"Tee \*new\* \$5 or \$6 \:red\[L\]", [h.value for h in app.subheader])

    def test_ebay_dates_are_not_shown_as_raw_utc(self):
        db.init()
        db.save_settings({"ebay_client_id": "id", "ebay_client_secret": "secret", "ebay_refresh_token": "token"})
        stamp = "2026-11-10T23:45:12.000Z"
        app = AppTest.from_file(APP, default_timeout=30)
        app.session_state["ebay"] = {"Best offers": [{"item_id": "1", "expires": stamp}],
                                     "Orders": [{"order_id": "2", "date": stamp}, {"order_id": "3", "date": None}]}
        app.run()
        self.assertEqual(app.exception, [])
        offers, orders = app.dataframe[-2:]
        self.assertEqual(offers.value["expires"][0], db.local_time(stamp))
        self.assertEqual(orders.value["date"][0], db.local_time(stamp))


    def test_headline_sums_kept_profit_and_leaves_out_returns(self):
        db.init()
        db.add_listing("Jeans", "", "", "Depop", 1000, 2500)
        db.mark_sold(1, 2000, 350)  # 2000 - 200 fee - 1000 paid - 350 shipping
        db.add_listing("Coat", "", "", "eBay", 1500, 3000)
        db.mark_sold(2, 1000, 0)
        db.update_shipment(2, "returned", "", "")
        db.add_listing("Tee", "", "", "Vinted", 200, 800)
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertEqual(app.title[0].value, "1 listing live, 1 to pack, €4.50 made.")

    def test_headline_shows_a_loss_and_big_amounts(self):
        db.init()
        db.add_listing("Coat", "", "", "eBay", 1500, 3000)
        db.mark_sold(1, 1000, 0)  # 1000 - 158 fee - 1500 paid
        db.update_shipment(1, "shipped", "", "")
        self.assertEqual(AppTest.from_file(APP, default_timeout=30).run().title[0].value,
                         "1 on the way, −€6.58 made.")
        db.add_listing("Bag", "", "", "Vinted", 0, 150000)
        db.mark_sold(2, 123456, 0)
        self.assertEqual(AppTest.from_file(APP, default_timeout=30).run().title[0].value,
                         "1 to pack, 1 on the way, €1,227.98 made.")

if __name__ == "__main__":
    unittest.main()
