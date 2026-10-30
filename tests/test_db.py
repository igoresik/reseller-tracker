import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db

# the tables as v0.1 created them, with euros stored as REAL and no last_event column
V01_SCHEMA = """
CREATE TABLE platforms (name TEXT PRIMARY KEY, fee_pct REAL NOT NULL DEFAULT 0, fee_fixed REAL NOT NULL DEFAULT 0);
INSERT INTO platforms VALUES ('Vinted', 0, 0), ('Depop', 10, 0), ('eBay', 12.8, 0.3), ('Etsy', 6.5, 0.2);
CREATE TABLE listings (id INTEGER PRIMARY KEY, title TEXT NOT NULL, brand TEXT, size TEXT,
    platform TEXT NOT NULL REFERENCES platforms(name), cost_price REAL NOT NULL, list_price REAL NOT NULL,
    sale_price REAL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT INTO listings (id, title, platform, cost_price, list_price, sale_price, status)
    VALUES (1, 'Jeans', 'Depop', 10.1, 19.99, 18.7, 'sold'), (2, 'Jacket', 'Etsy', 35, 120, NULL, 'active');
CREATE TABLE shipments (id INTEGER PRIMARY KEY, listing_id INTEGER NOT NULL UNIQUE REFERENCES listings(id),
    carrier TEXT, tracking_number TEXT, shipping_cost REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT INTO shipments (id, listing_id, tracking_number, shipping_cost, status) VALUES (1, 1, 'AB123', 4.35, 'shipped');
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "tracker.db"
        patcher = patch.object(db, "DB_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def test_v01_database_moves_to_cents_without_losing_anything(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript(V01_SCHEMA)
        db.init()

        listing = db.query("SELECT * FROM listings WHERE id = 1")[0]
        self.assertEqual((listing["cost_cents"], listing["list_cents"], listing["sale_cents"]), (1010, 1999, 1870))
        self.assertIsNone(db.query("SELECT sale_cents FROM listings WHERE id = 2")[0]["sale_cents"])
        shipment = db.query("SELECT * FROM shipments")[0]
        self.assertEqual((shipment["shipping_cents"], shipment["status"], shipment["last_event"]), (435, "shipped", None))
        fees = {row["name"]: (row["fee_bps"], row["fee_fixed_cents"]) for row in db.query("SELECT * FROM platforms")}
        self.assertEqual(fees["eBay"], (1280, 30))
        self.assertEqual(fees["Etsy"], (650, 20))  # a platform the user added survives
        self.assertEqual(db.query("SELECT sale_fee_cents FROM listings WHERE id = 1")[0]["sale_fee_cents"], 187)
        self.assertEqual(db.query("PRAGMA user_version")[0]["user_version"], 3)
        self.assertEqual(db.query("PRAGMA foreign_key_check"), [])
        self.assertTrue(self.path.with_name("tracker.before-cents.db").exists())

        db.init()  # running again changes nothing
        self.assertEqual(db.query("SELECT COUNT(*) AS n FROM listings")[0]["n"], 2)

    def test_failed_migration_leaves_the_old_database_untouched(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript(V01_SCHEMA)
        with patch.object(db, "CENTS_COPY", db.CENTS_COPY + "INSERT INTO nowhere VALUES (1);"):
            with self.assertRaises(sqlite3.OperationalError):
                db.init()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(listings)")]
            self.assertIn("cost_price", columns)
            self.assertEqual(conn.execute("SELECT list_price FROM listings WHERE id = 1").fetchone()[0], 19.99)

    def test_tracking_history_is_kept_and_not_duplicated(self):
        db.init()
        db.add_listing("Jeans", "", "", "Depop", 1000, 4000)
        db.mark_sold(1, 3000, 0)
        first = [
            {"event_id": "a", "occurred_at": "2026-10-01 09:00", "status": "Accepted",
             "location": "Lisboa", "milestone": "info_received"},
        ]
        db.record_tracking(1, "label_created", "2026-10-01 09:00 Accepted", first)
        later = first + [
            {"event_id": "b", "occurred_at": "2026-10-02 09:00", "status": "Departed",
             "location": None, "milestone": "in_transit"},
        ]
        db.record_tracking(1, "shipped", "2026-10-02 09:00 Departed", later)

        history = db.shipment_events(1)
        self.assertEqual([e["status"] for e in history], ["Departed", "Accepted"])
        shipment = db.shipments()[0]
        self.assertEqual((shipment["status"], shipment["last_event"]), ("shipped", "2026-10-02 09:00 Departed"))

    def test_changing_a_fee_does_not_rewrite_past_sales(self):
        db.init()
        db.add_listing("Jeans", "", "", "eBay", 1000, 4000)
        db.mark_sold(1, 2000, 0)
        db.execute("UPDATE platforms SET fee_bps = 0, fee_fixed_cents = 0 WHERE name = 'eBay'")
        self.assertEqual(db.sold_listings()[0]["sale_fee_cents"], 286)

    def test_sales_from_before_the_fee_was_kept_get_filled_in(self):
        db.init()
        db.add_listing("Jeans", "", "", "Depop", 1000, 4000)
        db.mark_sold(1, 3000, 0)
        db.execute("ALTER TABLE listings DROP COLUMN sale_fee_cents")
        db.init()
        self.assertEqual(db.sold_listings()[0]["sale_fee_cents"], 300)
        self.assertEqual(db.query("SELECT sale_fee_cents FROM listings")[0]["sale_fee_cents"], 300)


if __name__ == "__main__":
    unittest.main()
