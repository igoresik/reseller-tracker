import re
from html import escape

import requests
import streamlit as st

import db
import ebay
import ship24
from finance import net_profit, to_bps, to_cents

API_ERRORS = (requests.RequestException, RuntimeError)
STATUS_LABELS = {
    "pending": "To pack",
    "label_created": "Label ready",
    "shipped": "On the way",
    "delivered": "Delivered",
    "returned": "Returned",
}
INVALID_LISTING = "Give it a title and an asking price above €0."
EBAY_COLUMNS = {
    "item_id": "Item",
    "title": "Title",
    "price": "Price",
    "watchers": "Watchers",
    "url": st.column_config.LinkColumn("Link", display_text="Open"),
    "offer": "Offer",
    "buyer": "Buyer",
    "message": "Message",
    "expires": "Expires",
    "order_id": "Order",
    "date": "Date",
    "items": "Items",
    "total": "Total",
    "ebay_fee": "eBay fee",
    "payment": "Payment",
    "fulfillment": "Fulfilment",
}


def plain(text):
    """Text for a Markdown element, shown exactly as typed: "$10 or $20" is not a formula."""
    return re.sub(r"([\\`*_{}\[\]()<>#+\-.!|~$:])", r"\\\1", text)


def eur(cents):
    sign = "−" if cents < 0 else ""
    return f"{sign}€{abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def headline(listings, sold):
    to_pack = sum(s["status"] == "pending" for s in sold)
    on_the_way = sum(s["status"] in ("label_created", "shipped") for s in sold)
    made = sum(
        s["sale_cents"] - s["sale_fee_cents"] - s["cost_cents"] - s["shipping_cents"]
        for s in sold
        if s["status"] != "returned"
    )
    parts = []
    if listings:
        parts.append(f"{len(listings)} listing{'' if len(listings) == 1 else 's'} live")
    if to_pack:
        parts.append(f"{to_pack} to pack")
    if on_the_way:
        parts.append(f"{on_the_way} on the way")
    if sold:
        parts.append(f"{eur(made)} made")
    return ", ".join(parts) + "." if parts else "Nothing listed yet."


def listing_fields(platform_names, key, listing=None):
    """Inputs shared by the new and edit forms."""
    current = listing or {}
    title = st.text_input("Title", current.get("title", ""), key=f"{key}_title")
    left, right = st.columns(2)
    brand = left.text_input("Brand", current.get("brand") or "", key=f"{key}_brand")
    size = right.text_input("Size", current.get("size") or "", key=f"{key}_size")
    platform = st.selectbox(
        "Platform",
        platform_names,
        index=platform_names.index(current.get("platform", platform_names[0])),
        key=f"{key}_platform",
    )
    left, right = st.columns(2)
    # the inputs work in euros; everything past this point is whole cents
    cost = left.number_input(
        "You paid (€)", min_value=0.0, value=current.get("cost_cents", 0) / 100, step=0.5, key=f"{key}_cost"
    )
    asking = right.number_input(
        "Asking price (€)", min_value=0.0, value=current.get("list_cents", 0) / 100, step=0.5, key=f"{key}_price"
    )
    cost_cents, list_cents = to_cents(cost), to_cents(asking)
    if not title.strip() or list_cents <= 0:
        return None
    return title.strip(), brand.strip(), size.strip(), platform, cost_cents, list_cents


def receipt(listing, sale_cents, shipping_cents):
    fee, net, margin = net_profit(
        sale_cents, listing["cost_cents"], listing["fee_bps"], listing["fee_fixed_cents"], shipping_cents
    )
    discount = listing["list_cents"] - sale_cents
    if discount > 0:
        against_asking = f"{eur(discount)} under asking"
    elif discount < 0:
        against_asking = f"{eur(-discount)} over asking"
    else:
        against_asking = "at asking price"
    lines = [
        ("Buyer pays", sale_cents),
        (f"{listing['platform']} fee", -fee),
        ("You paid", -listing["cost_cents"]),
        ("Shipping", -shipping_cents),
    ]
    rows = "".join(
        f'<div class="receipt-line"><dt>{escape(label)}</dt><dd>{eur(amount)}</dd></div>'
        for label, amount in lines
    )
    return f"""
    <div class="receipt-wrap"><div class="receipt">
      <p class="receipt-title">{escape(listing["title"])}</p>
      <p class="receipt-note">{escape(listing["platform"])}, asking {eur(listing["list_cents"])}</p>
      <dl>{rows}</dl>
      <p class="receipt-total"><span>You keep</span>
        <span class="{"loss" if net < 0 else "gain"}">{eur(net)}</span></p>
      <p class="receipt-note">{margin:.1f}% margin, {against_asking}</p>
    </div></div>
    """


def journey(status):
    steps = db.SHIPMENT_STATUSES[:-1]  # returned is not a step
    items = ""
    for index, step in enumerate(steps):
        if index < steps.index(status):
            items += f'<li class="done">{STATUS_LABELS[step]}</li>'
        elif step == status:
            items += f'<li class="now" aria-current="step">{STATUS_LABELS[step]}</li>'
        else:
            items += f"<li>{STATUS_LABELS[step]}</li>"
    return f'<ol class="journey">{items}</ol>'


@st.cache_resource
def setup_database():
    # Streamlit reruns this whole file on every click, and setup writes to the database
    db.init()


st.set_page_config(page_title="Logistics Tracker", page_icon=":material/checkroom:", layout="wide")
# another website can reach a local server by pointing its own domain at 127.0.0.1;
# only answer when the browser asked for this computer by name
host = st.context.headers.get("Host", "").rsplit(":", 1)[0]
if host not in ("", "127.0.0.1", "localhost"):
    st.stop()
st.html(db.ROOT / "style.css")
setup_database()
settings = db.settings()
listings = db.active_listings()

st.title(headline(listings, db.sold_listings()), anchor=False)
inventory_tab, profit_tab, shipping_tab, ebay_tab, settings_tab = st.tabs(
    ["Inventory", "Profit", "Shipping", "eBay", "Settings"]
)

with inventory_tab:
    platforms = db.query("SELECT * FROM platforms ORDER BY name")
    platform_names = [p["name"] for p in platforms]
    form_column, table_column = st.columns([1, 2], gap="large")

    with form_column, st.form("add_listing", clear_on_submit=True):
        st.subheader("New listing", anchor=False)
        values = listing_fields(platform_names, "new")
        if st.form_submit_button("Add listing", type="primary"):
            if values:
                db.add_listing(*values)
                st.rerun()
            else:
                st.error(INVALID_LISTING)

    with table_column:
        st.subheader("Live listings", anchor=False)
        if listings:
            rows = [
                {
                    "title": row["title"],
                    "brand": row["brand"],
                    "size": row["size"],
                    "platform": row["platform"],
                    "cost": row["cost_cents"] / 100,  # display only
                    "asking": row["list_cents"] / 100,
                    "margin": float(
                        net_profit(row["list_cents"], row["cost_cents"], row["fee_bps"], row["fee_fixed_cents"])[2]
                    ),
                    "listed": db.local_date(row["created_at"]),
                }
                for row in listings
            ]
            st.dataframe(
                rows,
                hide_index=True,
                column_config={
                    "title": "Title",
                    "brand": "Brand",
                    "size": "Size",
                    "platform": "Platform",
                    "cost": st.column_config.NumberColumn("You paid", format="€%.2f"),
                    "asking": st.column_config.NumberColumn("Asking", format="€%.2f"),
                    "margin": st.column_config.ProgressColumn(
                        "Margin at asking", min_value=0, max_value=100, format="%.0f%%"
                    ),
                    "listed": st.column_config.DateColumn("Listed", format="D MMM"),
                },
            )
            with st.expander("Edit or remove a listing"):
                chosen = st.selectbox(
                    "Listing", listings, format_func=lambda row: row["title"], key="edit_choice"
                )
                # keyed per listing so the fields refill when another one is picked
                with st.form(f"edit_{chosen['id']}"):
                    values = listing_fields(platform_names, f"edit_{chosen['id']}", chosen)
                    save, remove, _ = st.columns([1, 1, 2])
                    if save.form_submit_button("Save changes", type="primary"):
                        if values:
                            db.update_listing(chosen["id"], *values)
                            st.rerun()
                        else:
                            st.error(INVALID_LISTING)
                    if remove.form_submit_button("Remove listing"):
                        db.delete_listing(chosen["id"])
                        st.rerun()
        else:
            st.info("Nothing listed yet. Add your first listing with the form.")

        with st.expander("Platform fees"):
            fees = st.data_editor(
                [
                    {"name": p["name"], "fee_pct": p["fee_bps"] / 100, "fee_fixed": p["fee_fixed_cents"] / 100}
                    for p in platforms
                ],
                hide_index=True,
                disabled=["name"],
                column_config={
                    "name": "Platform",
                    "fee_pct": st.column_config.NumberColumn("Fee %", min_value=0.0),
                    "fee_fixed": st.column_config.NumberColumn("Fixed fee (€)", min_value=0.0),
                },
            )
            if st.button("Save fees"):
                for fee in fees:
                    db.execute(
                        "UPDATE platforms SET fee_bps = ?, fee_fixed_cents = ? WHERE name = ?",
                        (to_bps(fee["fee_pct"] or 0), to_cents(fee["fee_fixed"] or 0), fee["name"]),
                    )
                st.rerun()

with profit_tab:
    if not listings:
        st.info("Add a listing in Inventory to work out its profit.")
    else:
        controls, result = st.columns([2, 3], gap="large")
        with controls:
            listing = st.selectbox(
                "Listing",
                listings,
                format_func=lambda row: f"{row['title']} ({row['platform']}, {eur(row['list_cents'])})",
            )
            # keyed per listing so the offer resets to that listing's price
            offer = st.number_input(
                "Buyer's offer (€)",
                min_value=0.0,
                value=listing["list_cents"] / 100,
                step=0.5,
                key=f"offer_{listing['id']}",
            )
            shipping = st.number_input(
                "Shipping you pay (€)", min_value=0.0, step=0.5, key=f"shipping_{listing['id']}"
            )
            sale_cents, shipping_cents = to_cents(offer), to_cents(shipping)
            if st.button("Mark sold at this price", type="primary", disabled=sale_cents <= 0):
                db.mark_sold(listing["id"], sale_cents, shipping_cents)
                st.rerun()
        result.html(receipt(listing, sale_cents, shipping_cents))

with shipping_tab:
    shipments = db.shipments()
    if not shipments:
        st.info("No parcels yet. Mark a listing as sold in Profit and it shows up here.")
    else:
        st.dataframe(
            [
                {
                    **{key: "" if value is None else value for key, value in row.items()},
                    "sold_for": row["sale_cents"] / 100,
                    "shipping": row["shipping_cents"] / 100,
                    "status": STATUS_LABELS[row["status"]],
                    "updated_at": db.local_date(row["updated_at"]).isoformat(),
                }
                for row in shipments
            ],
            hide_index=True,
            column_order=[
                "title", "platform", "sold_for", "status", "carrier",
                "tracking_number", "last_event", "shipping", "updated_at",
            ],
            column_config={
                "title": "Title",
                "platform": "Platform",
                "sold_for": st.column_config.NumberColumn("Sold for", format="€%.2f"),
                "status": "Status",
                "carrier": "Carrier",
                "tracking_number": "Tracking number",
                "last_event": "Latest event",
                "shipping": st.column_config.NumberColumn("Shipping", format="€%.2f"),
                "updated_at": "Updated",
            },
        )

        form_column, tracking_column = st.columns(2, gap="large")
        with form_column:
            st.subheader("Update a parcel", anchor=False)
            shipment = st.selectbox(
                "Parcel",
                shipments,
                format_func=lambda row: f"{row['title']} ({STATUS_LABELS[row['status']]})",
            )
            with st.form(f"shipment_{shipment['id']}"):
                status = st.selectbox(
                    "Status",
                    db.SHIPMENT_STATUSES,
                    index=db.SHIPMENT_STATUSES.index(shipment["status"]),
                    format_func=STATUS_LABELS.get,
                )
                carrier = st.text_input("Carrier", shipment["carrier"] or "")
                tracking_number = st.text_input("Tracking number", shipment["tracking_number"] or "")
                if st.form_submit_button("Save parcel"):
                    db.update_shipment(shipment["id"], status, carrier.strip(), tracking_number.strip())
                    st.rerun()

        with tracking_column:
            st.subheader(plain(shipment["title"]), anchor=False)
            if shipment["status"] == "returned":
                st.warning("This parcel came back to you.")
            else:
                st.html(journey(shipment["status"]))

            api_key = settings.get("ship24_api_key")
            if not api_key:
                st.caption("Add a Ship24 key in Settings to check tracking from here.")
            elif not shipment["tracking_number"]:
                st.caption("Save a tracking number to check tracking.")
            if st.button("Check tracking", disabled=not (api_key and shipment["tracking_number"])):
                try:
                    with st.spinner("Asking Ship24..."):
                        milestone, events = ship24.track(api_key, shipment["tracking_number"])
                except API_ERRORS as error:
                    st.error(str(error))
                else:
                    last_event = milestone
                    if events:
                        last_event = f"{events[0]['occurred_at'] or ''} {events[0]['status']}".strip()
                    status = ship24.new_status(shipment["status"], milestone)
                    db.record_tracking(shipment["id"], status, last_event, events)
                    st.rerun()
            history = db.shipment_events(shipment["id"])
            if history:
                st.dataframe(
                    history,
                    hide_index=True,
                    column_config={"occurred_at": "When", "status": "What", "location": "Where"},
                )

with ebay_tab:
    ebay_keys = [settings.get(k) for k in ("ebay_client_id", "ebay_client_secret", "ebay_refresh_token")]
    if not all(ebay_keys):
        st.info("Connect your eBay account in Settings to see your listings, offers and orders here.")
    else:
        if st.button("Refresh from eBay", type="primary"):
            try:
                with st.spinner("Asking eBay..."):
                    token = ebay.access_token(*ebay_keys)
                    st.session_state["ebay"] = {
                        "Active listings": ebay.active_listings(token),
                        "Best offers": ebay.best_offers(token),
                        "Orders": ebay.orders(token),
                    }
            except API_ERRORS as error:
                st.error(str(error))
        for heading, rows in st.session_state.get("ebay", {}).items():
            st.subheader(heading, anchor=False)
            if rows:
                st.dataframe(rows, hide_index=True, column_config=EBAY_COLUMNS)
            else:
                st.caption("Nothing here right now.")

with settings_tab:
    keys_column, ebay_column = st.columns(2, gap="large")

    with keys_column, st.form("settings"):
        st.subheader("Your keys", anchor=False)
        st.caption("Saved in tracker.db on this computer only. Never share or commit that file.")
        # saved secrets are never sent back to the page; a new key per save empties the fields
        replace = "Saved. Type a new one to replace it."
        saves = st.session_state.setdefault("saves", 0)
        ship24_api_key = st.text_input(
            "Ship24 API key",
            type="password",
            placeholder=replace if settings.get("ship24_api_key") else "",
            key=f"ship24_api_key_{saves}",
        )
        client_id = st.text_input("eBay App ID (Client ID)", settings.get("ebay_client_id", ""))
        client_secret = st.text_input(
            "eBay Cert ID (Client Secret)",
            type="password",
            placeholder=replace if settings.get("ebay_client_secret") else "",
            key=f"ebay_client_secret_{saves}",
        )
        runame = st.text_input("eBay RuName", settings.get("ebay_runame", ""))
        if st.form_submit_button("Save keys", type="primary"):
            values = {"ebay_client_id": client_id.strip(), "ebay_runame": runame.strip()}
            if ship24_api_key.strip():
                values["ship24_api_key"] = ship24_api_key.strip()
            if client_secret.strip():
                values["ebay_client_secret"] = client_secret.strip()
            db.save_settings(values)
            st.session_state["saves"] += 1
            st.rerun()

    with ebay_column:
        st.subheader("eBay account", anchor=False)
        client_id, client_secret, runame = (
            settings.get(k) for k in ("ebay_client_id", "ebay_client_secret", "ebay_runame")
        )
        if settings.get("ebay_refresh_token"):
            st.success("Your eBay account is connected.")
            if st.button("Disconnect eBay"):
                db.save_settings({"ebay_refresh_token": ""})
                st.session_state.pop("ebay", None)
                st.rerun()
        elif not (client_id and client_secret and runame):
            st.info("Save your eBay App ID, Cert ID and RuName first.")
        else:
            st.link_button("1. Sign in to eBay and agree", ebay.consent_url(client_id, runame))
            redirect = st.text_input("2. Paste the address of the page you land on (it contains code=)")
            if st.button("3. Connect", disabled=not redirect.strip()):
                try:
                    code = ebay.code_from_redirect(redirect)
                    refresh_token = ebay.exchange_code(client_id, client_secret, runame, code)
                except API_ERRORS as error:
                    st.error(str(error))
                else:
                    db.save_settings({"ebay_refresh_token": refresh_token})
                    st.rerun()
