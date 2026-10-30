import unittest
from unittest.mock import Mock, patch

import ebay
import ship24

# shapes follow the Ship24 and eBay docs; these tests do not call the real APIs


def reply(status=200, json=None, content=b""):
    return Mock(status_code=status, ok=status < 400, json=Mock(return_value=json), content=content)


class Ship24Test(unittest.TestCase):
    def test_track_returns_milestone_and_newest_event_first(self):
        body = {"data": {"trackings": [{
            "shipment": {"statusMilestone": "in_transit"},
            "events": [
                {"eventId": "a", "occurrenceDatetime": "2026-10-01T09:00:00", "status": "Accepted",
                 "location": "Lisboa", "statusMilestone": "info_received"},
                {"eventId": "b", "occurrenceDatetime": "2026-10-02T09:00:00", "status": "Departed",
                 "location": None, "statusMilestone": "in_transit"},
            ],
        }]}}
        with patch("ship24.requests.post", return_value=reply(json=body)) as post:
            milestone, events = ship24.track("key", "AB123")
        self.assertEqual(milestone, "in_transit")
        self.assertEqual(events[0], {
            "event_id": "b", "occurred_at": "2026-10-02 09:00", "status": "Departed",
            "location": None, "milestone": "in_transit",
        })
        self.assertEqual(events[1]["location"], "Lisboa")
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer key"})
        self.assertEqual(post.call_args.kwargs["json"], {"trackingNumber": "AB123"})

    def test_missing_and_null_fields_do_not_crash(self):
        body = {"data": {"trackings": [{
            "shipment": {"statusMilestone": None},
            "events": [
                {"status": "  Parcel scanned ", "occurrenceDatetime": None},
                {"eventId": None, "status": None, "occurrenceDatetime": "2026-10-03T10:30:00+01:00"},
            ],
        }]}}
        with patch("ship24.requests.post", return_value=reply(json=body)):
            milestone, events = ship24.track("key", "AB123")
        self.assertEqual(milestone, "pending")
        self.assertEqual(events[0]["occurred_at"], "2026-10-03 10:30")
        self.assertEqual(events[0]["status"], "(no description)")
        self.assertEqual(events[0]["event_id"], "2026-10-03T10:30:00+01:00|(no description)")
        self.assertEqual(events[1]["occurred_at"], None)  # events without a time go last
        self.assertEqual(events[1]["status"], "Parcel scanned")

    def test_milestone_casing_is_normalised(self):
        body = {"data": {"trackings": [{"shipment": {"statusMilestone": " Delivered "}, "events": []}]}}
        with patch("ship24.requests.post", return_value=reply(json=body)):
            milestone, events = ship24.track("key", "AB123")
        self.assertEqual((milestone, events), ("delivered", []))
        self.assertEqual(ship24.MILESTONE_STATUS[milestone], "delivered")

    def test_unknown_number_gives_pending(self):
        with patch("ship24.requests.post", return_value=reply(json={"data": {"trackings": []}})):
            self.assertEqual(ship24.track("key", "NOPE"), ("pending", []))

    def test_track_raises_api_message(self):
        body = {"errors": [{"code": "unauthorized", "message": "Invalid API key"}], "data": None}
        with patch("ship24.requests.post", return_value=reply(401, body)):
            with self.assertRaisesRegex(RuntimeError, "Invalid API key"):
                ship24.track("bad", "AB123")

    def test_rate_limit_without_json_is_reported(self):
        limited = Mock(status_code=429, ok=False, json=Mock(side_effect=ValueError("not json")))
        with patch("ship24.requests.post", return_value=limited):
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                ship24.track("key", "AB123")

    def test_checking_tracking_keeps_a_returned_parcel_returned(self):
        self.assertEqual(ship24.new_status("returned", "in_transit"), "returned")
        self.assertEqual(ship24.new_status("returned", "delivered"), "returned")

    def test_new_status_follows_the_milestone(self):
        self.assertEqual(ship24.new_status("pending", "in_transit"), "shipped")
        self.assertEqual(ship24.new_status("shipped", "exception"), "shipped")


class EbayTest(unittest.TestCase):
    def test_code_from_redirect_decodes_url(self):
        url = "https://example.com/done?code=v%5E1.1%23i%5E1&expires_in=299"
        self.assertEqual(ebay.code_from_redirect(url), "v^1.1#i^1")
        self.assertEqual(ebay.code_from_redirect(" v^1.1#i^1 "), "v^1.1#i^1")

    def test_exchange_code_returns_refresh_token(self):
        body = {"access_token": "a", "refresh_token": "r"}
        with patch("ebay.requests.post", return_value=reply(json=body)) as post:
            self.assertEqual(ebay.exchange_code("id", "secret", "ru", "code"), "r")
        self.assertEqual(post.call_args.kwargs["auth"], ("id", "secret"))
        self.assertEqual(post.call_args.kwargs["data"]["redirect_uri"], "ru")

    def test_token_error_is_raised(self):
        body = {"error": "invalid_grant", "error_description": "the provided code is invalid"}
        with patch("ebay.requests.post", return_value=reply(400, body)):
            with self.assertRaisesRegex(RuntimeError, "code is invalid"):
                ebay.exchange_code("id", "secret", "ru", "code")

    def test_active_listings_parses_items(self):
        xml = b"""<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents">
          <Ack>Success</Ack>
          <ActiveList>
            <ItemArray><Item>
              <ItemID>111</ItemID><Title>Levi's 501</Title>
              <SellingStatus><CurrentPrice currencyID="EUR">40.0</CurrentPrice></SellingStatus>
              <ListingDetails><ViewItemURL>https://www.ebay.ie/itm/111</ViewItemURL></ListingDetails>
            </Item></ItemArray>
            <PaginationResult><TotalNumberOfPages>1</TotalNumberOfPages></PaginationResult>
          </ActiveList>
        </GetMyeBaySellingResponse>"""
        with patch("ebay.requests.post", return_value=reply(content=xml)) as post:
            items = ebay.active_listings("token")
        self.assertEqual(items, [{
            "item_id": "111", "title": "Levi's 501", "price": "40.0 EUR",
            "watchers": "0", "url": "https://www.ebay.ie/itm/111",
        }])
        self.assertEqual(post.call_args.kwargs["headers"]["X-EBAY-API-IAF-TOKEN"], "token")

    def test_best_offers_parses_offers(self):
        xml = b"""<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
          <Ack>Success</Ack>
          <ItemBestOffersArray><ItemBestOffers>
            <Item><ItemID>111</ItemID><Title>Levi's 501</Title></Item>
            <BestOfferArray><BestOffer>
              <Price currencyID="EUR">30.0</Price>
              <Buyer><UserID>buyer1</UserID></Buyer>
              <BuyerMessage>Would you take 30?</BuyerMessage>
              <ExpirationTime>2026-10-15T10:00:00.000Z</ExpirationTime>
            </BestOffer></BestOfferArray>
          </ItemBestOffers></ItemBestOffersArray>
        </GetBestOffersResponse>"""
        with patch("ebay.requests.post", return_value=reply(content=xml)):
            offers = ebay.best_offers("token")
        self.assertEqual(offers[0]["offer"], "30.0 EUR")
        self.assertEqual(offers[0]["buyer"], "buyer1")

    def test_trading_failure_is_raised(self):
        xml = b"""<GetBestOffersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
          <Ack>Failure</Ack><Errors><LongMessage>Invalid IAF token.</LongMessage></Errors>
        </GetBestOffersResponse>"""
        with patch("ebay.requests.post", return_value=reply(content=xml)):
            with self.assertRaisesRegex(RuntimeError, "Invalid IAF token"):
                ebay.best_offers("token")

    def test_trading_reply_that_is_not_xml_is_reported(self):
        page = b"<html><body>503 Service Unavailable<br></body></html>"
        with patch("ebay.requests.post", return_value=reply(503, content=page)):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                ebay.best_offers("token")

    def test_orders_flattens_fields(self):
        body = {"orders": [{
            "orderId": "12-345", "creationDate": "2026-10-10T08:00:00.000Z",
            "buyer": {"username": "buyer1"},
            "pricingSummary": {"total": {"value": "30.0", "currency": "EUR"}},
            "totalMarketplaceFee": {"value": "3.84", "currency": "EUR"},
            "orderPaymentStatus": "PAID", "orderFulfillmentStatus": "NOT_STARTED",
            "lineItems": [{"title": "Levi's 501"}],
        }]}
        with patch("ebay.requests.get", return_value=reply(json=body)):
            rows = ebay.orders("token")
        self.assertEqual(rows[0]["total"], "30.0 EUR")
        self.assertEqual(rows[0]["ebay_fee"], "3.84")
        self.assertEqual(rows[0]["items"], "Levi's 501")


if __name__ == "__main__":
    unittest.main()
