from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


MAX_EUROS = 1_000_000  # biggest amount any input takes; keeps cents well inside SQLite's INTEGER


def to_cents(euros):
    """Euros as typed (float or text) to whole cents, rounding half up. Raises ValueError past MAX_EUROS."""
    try:
        value = Decimal(str(euros))
    except InvalidOperation:
        raise ValueError(f"not a number: {euros!r}") from None
    if not value.is_finite() or abs(value) > MAX_EUROS:
        raise ValueError(f"amount out of range: {euros!r}")
    return int((value * 100).quantize(Decimal(1), ROUND_HALF_UP))


def to_bps(percent):
    """A fee percentage to basis points: 12.8 -> 1280."""
    return to_cents(percent)


def net_profit(sale_cents, cost_cents, fee_bps, fee_fixed_cents=0, shipping_cents=0):
    """All amounts in cents. Return (platform fee, net profit, margin % of the sale price)."""
    fee = (sale_cents * fee_bps + 5_000) // 10_000 + fee_fixed_cents  # rounded half up to the cent
    net = sale_cents - fee - cost_cents - shipping_cents
    margin = Decimal(net * 100) / sale_cents if sale_cents else Decimal(0)
    return fee, net, margin.quantize(Decimal("0.1"), ROUND_HALF_UP)
