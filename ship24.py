import requests

TRACK_URL = "https://api.ship24.com/public/v1/trackers/track"

# Ship24 milestone -> shipment status; others (pending, exception) leave it alone
MILESTONE_STATUS = {
    "info_received": "label_created",
    "in_transit": "shipped",
    "out_for_delivery": "shipped",
    "failed_attempt": "shipped",
    "available_for_pickup": "shipped",
    "delivered": "delivered",
}


def new_status(current, milestone):
    # returned is only ever set by hand and takes the sale out of profit, so tracking can't undo it
    if current == "returned":
        return current
    return MILESTONE_STATUS.get(milestone, current)


def _event(raw):
    """One Ship24 event as saved in shipment_events; any field may be missing."""
    when = raw.get("occurrenceDatetime")
    status = (raw.get("status") or "").strip() or "(no description)"
    return {
        # the id makes checking again idempotent; fall back to time + text if Ship24 omits it
        "event_id": raw.get("eventId") or f"{when}|{status}",
        "occurred_at": when[:16].replace("T", " ") if when else None,
        "status": status,
        "location": raw.get("location") or None,
        "milestone": (raw.get("statusMilestone") or "").strip().lower() or None,
    }


def track(api_key, tracking_number):
    """Return (milestone, events newest first) for a tracking number."""
    response = requests.post(
        TRACK_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"trackingNumber": tracking_number},
        timeout=90,  # the first lookup of a number can take up to a minute
    )
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError(f"Ship24: HTTP {response.status_code}")
    if not response.ok:
        errors = body.get("errors") or [{}]
        raise RuntimeError(f"Ship24: {errors[0].get('message', response.status_code)}")

    trackings = (body.get("data") or {}).get("trackings") or [{}]
    tracking = trackings[0]
    milestone = ((tracking.get("shipment") or {}).get("statusMilestone") or "pending").strip().lower()
    events = [_event(raw) for raw in tracking.get("events") or []]
    events.sort(key=lambda e: e["occurred_at"] or "", reverse=True)
    return milestone, events
