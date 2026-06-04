from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator

import psycopg
import pytest
import requests


API_URL = os.getenv("API_URL", "http://localhost:8000")
NOTIFICATION_URL = os.getenv("NOTIFICATION_URL", "http://localhost:8001")
DATABASE_DSN = os.getenv("TEST_DATABASE_DSN", "postgresql://marketplace:marketplace@localhost:5432/marketplace")


def wait_for_http(url: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise AssertionError(f"{url} did not become ready")


@pytest.fixture(scope="session")
def services_ready() -> None:
    wait_for_http(f"{API_URL}/health")
    wait_for_http(f"{NOTIFICATION_URL}/health")


@pytest.fixture()
def run_id() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture()
def db_conn(services_ready) -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_DSN) as conn:
        yield conn


def register_user(username: str, role: str) -> None:
    response = requests.post(
        f"{API_URL}/auth/register",
        json={"username": username, "password": "secret123", "role": role},
        timeout=10,
    )
    assert response.status_code == 201, response.text


def login(username: str) -> str:
    response = requests.post(
        f"{API_URL}/auth/login",
        json={"username": username, "password": "secret123"},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def cleanup_run(run_id: str) -> None:
    seller = f"seller_{run_id}"
    buyer = f"buyer_{run_id}"
    with psycopg.connect(DATABASE_DSN) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE username IN (%s, %s)", (seller, buyer))
            user_ids = [row[0] for row in cursor.fetchall()]
            if not user_ids:
                return
            cursor.execute("DELETE FROM notifications WHERE user_id = ANY(%s)", (user_ids,))
            cursor.execute("DELETE FROM user_operations WHERE user_id = ANY(%s)", (user_ids,))
            cursor.execute(
                "DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id = ANY(%s))",
                (user_ids,),
            )
            cursor.execute("DELETE FROM orders WHERE user_id = ANY(%s)", (user_ids,))
            cursor.execute("DELETE FROM products WHERE seller_id = ANY(%s)", (user_ids,))
            cursor.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
        conn.commit()


@pytest.fixture()
def marketplace_users(services_ready, run_id: str) -> Iterator[tuple[str, str]]:
    seller = f"seller_{run_id}"
    buyer = f"buyer_{run_id}"
    register_user(seller, "SELLER")
    register_user(buyer, "USER")
    try:
        yield login(seller), login(buyer)
    finally:
        cleanup_run(run_id)


def create_product(seller_token: str, run_id: str, stock: int = 7) -> dict:
    response = requests.post(
        f"{API_URL}/products",
        headers=bearer(seller_token),
        json={
            "name": f"Test keyboard {run_id}",
            "description": "CI product",
            "price": 125.50,
            "stock": stock,
            "category": "electronics",
            "status": "ACTIVE",
        },
        timeout=10,
    )
    assert response.status_code == 201, response.text
    return response.json()
