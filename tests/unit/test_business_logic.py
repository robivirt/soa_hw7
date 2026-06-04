from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.openapi_impl import aggregate_items, apply_promo_to_total, calculate_discount, money


def test_aggregate_items_sums_duplicate_products():
    product_id = "11111111-1111-1111-1111-111111111111"

    result = aggregate_items(
        [
            SimpleNamespace(product_id=product_id, quantity=2),
            SimpleNamespace(product_id=product_id, quantity=3),
        ]
    )

    assert list(result.values()) == [5]


def test_percentage_promo_discount_is_capped_at_seventy_percent():
    promo = SimpleNamespace(discount_type="PERCENTAGE", discount_value=Decimal("95.00"))

    assert calculate_discount(Decimal("100.00"), promo) == Decimal("70.00")


def test_apply_fixed_promo_to_total_uses_money_precision():
    promo = SimpleNamespace(
        discount_type="FIXED_AMOUNT",
        discount_value=Decimal("10.005"),
        min_order_amount=Decimal("20.00"),
    )

    total, discount = apply_promo_to_total(money(Decimal("35.10")), promo)

    assert total == Decimal("25.10")
    assert discount == Decimal("10.00")
