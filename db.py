import os
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import vault
from finance import net_profit

ROOT = Path(__file__).parent
# the packaged app unpacks to a temporary folder, so its data lives in AppData instead
FROZEN = getattr(sys, "frozen", False)
DATA_DIR = Path(os.environ["APPDATA"]) / "LogisticsTracker" if FROZEN else ROOT
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "tracker.db"

SECRET_SETTINGS = ("ship24_api_key", "ebay_client_secret", "ebay_refresh_token")
# must match the CHECK in schema.sql
SHIPMENT_STATUSES = ["pending", "label_created", "shipped", "delivered", "returned"]


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# copies data saved by v0.1, which kept euros as REAL, into the cents tables
CENTS_COPY = """
INSERT INTO platforms (name, fee_bps, fee_fixed_cents)
    SELECT name, CAST(ROUND(fee_pct * 100) AS INTEGER), CAST(ROUND(fee_fixed * 100) AS INTEGER)
    FROM old_platforms WHERE true
    ON CONFLICT(name) DO UPDATE SET fee_bps = excluded.fee_bps, fee_fixed_cents = excluded.fee_fixed_cents;
INSERT INTO listings (id, title, brand, size, platform, cost_cents, list_cents, sale_cents, status, created_at)
    SELECT id, title, brand, size, platform, CAST(ROUND(cost_price * 100) AS INTEGER),
        CAST(ROUND(list_price * 100) AS INTEGER), CAST(ROUND(sale_price * 100) AS INTEGER), status, created_at
    FROM old_listings;
INSERT INTO shipments (id, listing_id, carrier, tracking_number, shipping_cents, status, updated_at, last_event)
    SELECT id, listing_id, carrier, tracking_number, CAST(ROUND(shipping_cost * 100) AS INTEGER),
        status, updated_at, last_event
    FROM old_shipments;
DROP TABLE old_shipments;
DROP TABLE old_listings;
DROP TABLE old_platforms;
"""


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_to_cents(conn, schema):
    """Rebuild a v0.1 database in cents, all or nothing. A copy of the old file is kept as the way back."""
    shutil.copy2(DB_PATH, DB_PATH.with_name(f"{DB_PATH.stem}.before-cents.db"))
    if "last_event" not in _columns(conn, "shipments"):  # databases older than tracking
        conn.execute("ALTER TABLE shipments ADD COLUMN last_event TEXT")
        conn.commit()
    tables = ("platforms", "listings", "shipments")
    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.isolation_level = None  # transaction handled by hand
    conn.execute("PRAGMA foreign_keys = OFF")  # tables are renamed and rebuilt; checked below
    try:
        conn.executescript(
            "BEGIN;"
            + "".join(f"ALTER TABLE {t} RENAME TO old_{t};" for t in tables)
            + schema
            + CENTS_COPY
        )
        for table, count in before.items():
            if conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] < count:
                raise sqlite3.DatabaseError(f"moving to cents lost rows in {table}")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.DatabaseError("moving to cents broke a link between tables")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    with closing(connect()) as conn:
        if "cost_price" in _columns(conn, "listings"):
            _migrate_to_cents(conn, schema)
    with closing(connect()) as conn, conn:
        conn.executescript(schema)
        if "sale_fee_cents" not in _columns(conn, "listings"):
            conn.execute("ALTER TABLE listings ADD COLUMN sale_fee_cents INTEGER")
        # sales from before the fee was kept: today's rates are the best record left
        for row in conn.execute(
            "SELECT l.id, l.sale_cents, p.fee_bps, p.fee_fixed_cents FROM listings l"
            " JOIN platforms p ON p.name = l.platform"
            " WHERE l.status = 'sold' AND l.sale_fee_cents IS NULL"
        ).fetchall():
            fee = net_profit(row["sale_cents"], 0, row["fee_bps"], row["fee_fixed_cents"])[0]
            conn.execute("UPDATE listings SET sale_fee_cents = ? WHERE id = ?", (fee, row["id"]))
        # keys saved in plain text by older versions
        for row in conn.execute("SELECT key, value FROM settings").fetchall():
            if row["key"] in SECRET_SETTINGS:
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ?", (vault.lock(row["value"]), row["key"])
                )


def query(sql, params=()):
    with closing(connect()) as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def execute(sql, params=()):
    with closing(connect()) as conn, conn:
        conn.execute(sql, params)


def add_listing(title, brand, size, platform, cost_cents, list_cents):
    execute(
        "INSERT INTO listings (title, brand, size, platform, cost_cents, list_cents)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (title, brand, size, platform, cost_cents, list_cents),
    )


def update_listing(listing_id, title, brand, size, platform, cost_cents, list_cents):
    execute(
        "UPDATE listings SET title = ?, brand = ?, size = ?, platform = ?,"
        " cost_cents = ?, list_cents = ? WHERE id = ? AND status = 'active'",
        (title, brand, size, platform, cost_cents, list_cents, listing_id),
    )


def delete_listing(listing_id):
    # sold listings stay: their shipment and profit history point at them
    execute("DELETE FROM listings WHERE id = ? AND status = 'active'", (listing_id,))


def active_listings():
    return query(
        "SELECT l.*, p.fee_bps, p.fee_fixed_cents FROM listings l"
        " JOIN platforms p ON p.name = l.platform"
        " WHERE l.status = 'active' ORDER BY l.created_at DESC"
    )


def mark_sold(listing_id, sale_cents, shipping_cents):
    # one transaction: a sold listing always has a shipment
    with closing(connect()) as conn, conn:
        rates = conn.execute(
            "SELECT p.fee_bps, p.fee_fixed_cents FROM listings l"
            " JOIN platforms p ON p.name = l.platform WHERE l.id = ? AND l.status = 'active'",
            (listing_id,),
        ).fetchone()
        if not rates:  # another window already sold or removed it
            return
        fee = net_profit(sale_cents, 0, rates["fee_bps"], rates["fee_fixed_cents"])[0]
        conn.execute(
            "UPDATE listings SET status = 'sold', sale_cents = ?, sale_fee_cents = ? WHERE id = ?",
            (sale_cents, fee, listing_id),
        )
        conn.execute(
            "INSERT INTO shipments (listing_id, shipping_cents) VALUES (?, ?)",
            (listing_id, shipping_cents),
        )


def shipments():
    return query(
        "SELECT s.id, l.title, l.platform, l.sale_cents, s.carrier, s.tracking_number,"
        " s.shipping_cents, s.status, s.last_event, s.updated_at FROM shipments s"
        " JOIN listings l ON l.id = s.listing_id ORDER BY s.updated_at DESC"
    )


def update_shipment(shipment_id, status, carrier, tracking_number):
    execute(
        "UPDATE shipments SET status = ?, carrier = ?, tracking_number = ?,"
        " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, carrier, tracking_number, shipment_id),
    )


def record_tracking(shipment_id, status, last_event, events):
    """Save a Ship24 answer in one transaction: events not seen before, then the parcel's state."""
    with closing(connect()) as conn, conn:
        conn.executemany(
            "INSERT OR IGNORE INTO shipment_events"
            " (shipment_id, event_id, occurred_at, status, location, milestone)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (shipment_id, e["event_id"], e["occurred_at"], e["status"], e["location"], e["milestone"])
                for e in events
            ],
        )
        conn.execute(
            "UPDATE shipments SET status = ?, last_event = ?,"
            " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, last_event, shipment_id),
        )


def shipment_events(shipment_id):
    return query(
        "SELECT occurred_at, status, location FROM shipment_events WHERE shipment_id = ?"
        " ORDER BY occurred_at DESC, id DESC",
        (shipment_id,),
    )


def settings():
    return {row["key"]: vault.unlock(row["value"]) for row in query("SELECT key, value FROM settings")}


def save_settings(values):
    with closing(connect()) as conn, conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(key, vault.lock(value) if key in SECRET_SETTINGS else value) for key, value in values.items()],
        )


def sold_listings():
    return query(
        "SELECT l.sale_cents, l.sale_fee_cents, l.cost_cents, s.shipping_cents, s.status"
        " FROM listings l JOIN shipments s ON s.listing_id = l.id WHERE l.status = 'sold'"
    )
