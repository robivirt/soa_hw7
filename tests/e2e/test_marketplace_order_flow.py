from __future__ import annotations

import requests

from tests.conftest import API_URL, bearer, create_product


def test_create_product_create_order_and_verify_postgres_stock(db_conn, marketplace_users, run_id):
    seller_token, buyer_token = marketplace_users
    product = create_product(seller_token, run_id, stock=9)

    order_response = requests.post(
        f"{API_URL}/orders",
        headers=bearer(buyer_token),
        json={"items": [{"product_id": product["id"], "quantity": 4}]},
        timeout=10,
    )

    assert order_response.status_code == 201, order_response.text
    order = order_response.json()
    assert order["id"]
    assert order["status"] == "CREATED"
    assert order["total_amount"] == 502.0
    assert order["discount_amount"] == 0.0
    assert order["items"][0]["product_id"] == product["id"]
    assert order["items"][0]["price_at_order"] == 125.5

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT stock FROM products WHERE id = %s", (product["id"],))
        stock = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM order_items WHERE order_id = %s", (order["id"],))
        item_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT event_type, status FROM notifications WHERE order_id = %s",
            (order["id"],),
        )
        notification = cursor.fetchone()

    assert stock == 5
    assert item_count == 1
    assert notification == ("ORDER_CREATED", "SENT")
