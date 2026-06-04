from __future__ import annotations

import requests

from tests.conftest import API_URL, NOTIFICATION_URL, bearer, create_product


def test_order_creates_notification_through_notification_service(marketplace_users, run_id):
    seller_token, buyer_token = marketplace_users
    product = create_product(seller_token, run_id, stock=5)

    response = requests.post(
        f"{API_URL}/orders",
        headers=bearer(buyer_token),
        json={"items": [{"product_id": product["id"], "quantity": 2}]},
        timeout=10,
    )

    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "CREATED"
    assert order["items"][0]["product_id"] == product["id"]
    assert order["items"][0]["quantity"] == 2

    notification_response = requests.get(f"{NOTIFICATION_URL}/notifications/orders/{order['id']}", timeout=10)
    assert notification_response.status_code == 200, notification_response.text
    notifications = notification_response.json()
    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "ORDER_CREATED"
    assert notifications[0]["status"] == "SENT"


def test_metrics_are_exposed_for_both_services(services_ready):
    api_metrics = requests.get(f"{API_URL}/metrics", timeout=10)
    notification_metrics = requests.get(f"{NOTIFICATION_URL}/metrics", timeout=10)

    assert api_metrics.status_code == 200
    assert notification_metrics.status_code == 200
    assert "http_requests_total" in api_metrics.text
    assert "http_requests_total" in notification_metrics.text
