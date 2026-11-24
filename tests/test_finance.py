import unittest
from decimal import Decimal

from finance import net_profit, to_bps, to_cents


class NetProfitTest(unittest.TestCase):
    def test_fee_is_taken_from_sale_price(self):
        self.assertEqual(net_profit(4000, 1000, 1000), (400, 2600, Decimal("65.0")))

    def test_counteroffer_lowers_fee_and_profit(self):
        self.assertEqual(net_profit(3000, 1000, 1000), (300, 1700, Decimal("56.7")))

    def test_fixed_fee_and_shipping(self):
        # 12.8% of €20.00 is €2.56, plus €0.30
        self.assertEqual(net_profit(2000, 500, 1280, 30, 350), (286, 864, Decimal("43.2")))

    def test_fee_rounds_half_up_to_the_cent(self):
        # 12.8% of €19.99 is 255.872 cents
        self.assertEqual(net_profit(1999, 0, 1280)[0], 256)
        # 10% of €0.05 is exactly half a cent
        self.assertEqual(net_profit(5, 0, 1000)[0], 1)

    def test_loss_gives_negative_margin(self):
        self.assertEqual(net_profit(1000, 1500, 1000), (100, -600, Decimal("-60.0")))

    def test_zero_sale_price(self):
        self.assertEqual(net_profit(0, 500, 1000), (0, -500, Decimal("0.0")))

    def test_no_float_drift_over_many_sales(self):
        # 1000 sales of €0.10 add up to exactly €100 in cents; a running float total drifts
        cents = euros = 0
        for _ in range(1000):
            cents += to_cents(0.1)
            euros += 0.1
        self.assertEqual(cents, 10_000)
        self.assertNotEqual(euros, 100.0)


class ConversionTest(unittest.TestCase):
    def test_to_cents(self):
        self.assertEqual(to_cents(19.99), 1999)
        self.assertEqual(to_cents("2.675"), 268)  # half up, where float rounding gives 2.67
        self.assertEqual(to_cents(0), 0)

    def test_to_cents_rejects_amounts_out_of_range(self):
        self.assertEqual(to_cents(1_000_000), 100_000_000)
        for bad in (1e30, 1e20, 9.3e16, 1_000_000.01, float("nan"), float("inf"), "abc"):
            with self.assertRaises(ValueError):
                to_cents(bad)

    def test_to_bps(self):
        self.assertEqual(to_bps(12.8), 1280)
        self.assertEqual(to_bps(10), 1000)


if __name__ == "__main__":
    unittest.main()
