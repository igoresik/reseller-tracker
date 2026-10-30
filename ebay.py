import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import requests

AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
TRADING_URL = "https://api.ebay.com/ws/api.dll"
ORDERS_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
SCOPES = (
    "https://api.ebay.com/oauth/api_scope"
    " https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"
)
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


def consent_url(client_id, runame):
    query = {"client_id": client_id, "redirect_uri": runame, "response_type": "code", "scope": SCOPES}
    return f"{AUTH_URL}?{urlencode(query)}"


def code_from_redirect(text):
    """Accept the full redirect URL or the bare code."""
    codes = parse_qs(urlparse(text.strip()).query).get("code")
    return codes[0] if codes else unquote(text.strip())


def _token(client_id, client_secret, data):
    response = requests.post(TOKEN_URL, auth=(client_id, client_secret), data=data, timeout=30)
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError(f"eBay: HTTP {response.status_code}")
    if not response.ok:
        raise RuntimeError(f"eBay: {body.get('error_description', response.status_code)}")
    return body


def exchange_code(client_id, client_secret, runame, code):
    """Swap the consent code for a refresh token (valid about 18 months)."""
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": runame}
    return _token(client_id, client_secret, data)["refresh_token"]


def access_token(client_id, client_secret, refresh_token):
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    return _token(client_id, client_secret, data)["access_token"]


def _trading(token, call, inner_xml):
    # listings made on the site and buyer Best Offers only exist in the older XML API
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<{call}Request xmlns="{NS["e"]}">{inner_xml}</{call}Request>'
    )
    headers = {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1451",
        "X-EBAY-API-CALL-NAME": call,
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml",
    }
    response = requests.post(TRADING_URL, headers=headers, data=body.encode(), timeout=30)
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:  # outages come back as an HTML page
        raise RuntimeError(f"eBay: HTTP {response.status_code}")
    if root.findtext("e:Ack", namespaces=NS) not in ("Success", "Warning"):
        message = root.findtext("e:Errors/e:LongMessage", namespaces=NS)
        raise RuntimeError(f"eBay: {message or response.status_code}")
    return root


def _money(node, path):
    price = node.find(path, NS)
    return "" if price is None else f"{price.text} {price.get('currencyID', '')}".strip()


def active_listings(token):
    items, page, pages = [], 1, 1
    while page <= pages:
        root = _trading(
            token,
            "GetMyeBaySelling",
            "<ActiveList><Pagination><EntriesPerPage>200</EntriesPerPage>"
            f"<PageNumber>{page}</PageNumber></Pagination></ActiveList>",
        )
        for item in root.iterfind("e:ActiveList/e:ItemArray/e:Item", NS):
            items.append({
                "item_id": item.findtext("e:ItemID", namespaces=NS),
                "title": item.findtext("e:Title", namespaces=NS),
                "price": _money(item, "e:SellingStatus/e:CurrentPrice"),
                "watchers": item.findtext("e:WatchCount", "0", NS),
                "url": item.findtext("e:ListingDetails/e:ViewItemURL", namespaces=NS),
            })
        pages = int(root.findtext("e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", "1", NS))
        page += 1
    return items


def best_offers(token):
    """Active Best Offers on all of the account's items."""
    root = _trading(token, "GetBestOffers", "<DetailLevel>ReturnAll</DetailLevel>")
    offers = []
    for group in root.iterfind("e:ItemBestOffersArray/e:ItemBestOffers", NS):
        for offer in group.iterfind("e:BestOfferArray/e:BestOffer", NS):
            offers.append({
                "item_id": group.findtext("e:Item/e:ItemID", namespaces=NS),
                "title": group.findtext("e:Item/e:Title", namespaces=NS),
                "offer": _money(offer, "e:Price"),
                "buyer": offer.findtext("e:Buyer/e:UserID", namespaces=NS),
                "message": offer.findtext("e:BuyerMessage", namespaces=NS),
                "expires": offer.findtext("e:ExpirationTime", namespaces=NS),
            })
    return offers


def orders(token):
    rows = []
    while True:
        response = requests.get(
            ORDERS_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 50, "offset": len(rows)},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"eBay: orders request failed, HTTP {response.status_code}")
        body = response.json()
        for order in body.get("orders", []):
            total = order.get("pricingSummary", {}).get("total", {})
            fee = order.get("totalMarketplaceFee", {})
            rows.append({
                "order_id": order.get("orderId"),
                "date": order.get("creationDate"),
                "items": ", ".join(line.get("title", "") for line in order.get("lineItems", [])),
                "buyer": order.get("buyer", {}).get("username"),
                "total": f"{total.get('value', '')} {total.get('currency', '')}".strip(),
                "ebay_fee": fee.get("value"),
                "payment": order.get("orderPaymentStatus"),
                "fulfillment": order.get("orderFulfillmentStatus"),
            })
        if not (body.get("next") and body.get("orders")):
            return rows
