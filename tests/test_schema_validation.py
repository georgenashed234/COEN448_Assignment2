import json
import os
import uuid
from pathlib import Path

import pytest
import requests
from jsonschema import validate

USER_V2_URL = os.getenv("USER_V2_URL", "http://localhost:5003")
ORDER_URL = os.getenv("ORDER_URL", "http://localhost:5001")

ROOT = Path(__file__).resolve().parents[1]
USER_SCHEMA_PATH = ROOT / "src" / "shared" / "schemas" / "user_schema.json"
ORDER_SCHEMA_PATH = ROOT / "src" / "shared" / "schemas" / "order_schema.json"


def load_schema(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def user_schema():
    return load_schema(USER_SCHEMA_PATH)


@pytest.fixture(scope="module")
def order_schema():
    return load_schema(ORDER_SCHEMA_PATH)


def create_user_v2():
    uid = str(uuid.uuid4())[:8]
    payload = {
    "firstName": "Schema",
    "lastName": "Tester",
    "emails": [f"schema_{uid}@example.com"],
    "phoneNumber": "5145551234",
    "deliveryAddress": {
        "street": "123 Main",
        "city": "Montreal",
        "state": "QC",
        "postalCode": "H3G1M8",
        "country": "Canada"
    }
}
    r = requests.post(f"{USER_V2_URL}/users/", json=payload)
    assert r.status_code == 201
    return r.json()


def create_order_direct(user):
    payload = {
        "userId": user["userId"],
        "items": [{"itemId": "item-1", "quantity": 1, "price": 10}],
        "userEmails": user["emails"],
        "deliveryAddress": user["deliveryAddress"],
        "orderStatus": "under process"
    }
    r = requests.post(f"{ORDER_URL}/orders/", json=payload)
    assert r.status_code == 201
    return r.json()


def test_created_user_matches_user_schema(user_schema):
    created_user = create_user_v2()
    validate(instance=created_user, schema=user_schema)


def test_created_order_matches_order_schema(order_schema):
    user = create_user_v2()
    created_order = create_order_direct(user)
    validate(instance=created_order, schema=order_schema)


def test_invalid_user_payload_fails_schema_enforcement():
    bad_user = {
        "firstName": "Bad",
        "lastName": "User",
        "emails": ["bad@example.com"],
        "deliveryAddress": {
            "city": "Montreal",
            "state": "QC",
            "postalCode": "H3G1M8",
            "country": "Canada"
        }
    }

    r = requests.post(f"{USER_V2_URL}/users/", json=bad_user)
    assert r.status_code == 400


def test_invalid_order_payload_fails_schema_enforcement():
    user = create_user_v2()

    bad_order = {
        "userId": user["userId"],
        "items": [{"itemId": "item-1", "quantity": 1, "price": 10}],
        "userEmails": user["emails"],
        "deliveryAddress": user["deliveryAddress"],
        "orderStatus": "processing"
    }

    r = requests.post(f"{ORDER_URL}/orders/", json=bad_order)
    assert r.status_code == 400