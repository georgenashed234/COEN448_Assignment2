import os
import time
import uuid
import subprocess
from pathlib import Path

import pytest
import requests

API_URL = os.getenv("API_url", "http://localhost:8000")
ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def wait_for_service(url, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"Service not ready: {url}")


def read_env_lines():
    return ENV_FILE.read_text().splitlines()


def set_p_value(new_value: int):
    lines = read_env_lines()
    updated = []
    found = False
    for line in lines:
        if line.startswith("P_VALUE="):
            updated.append(f"P_VALUE={new_value}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"P_VALUE={new_value}")
    ENV_FILE.write_text("\n".join(updated) + "\n")

    # Keep the Python process environment in sync too
    os.environ["P_VALUE"] = str(new_value)


def get_current_p_value():
    for line in read_env_lines():
        if line.startswith("P_VALUE="):
            return int(line.split("=", 1)[1].strip())
    return 100


def recreate_kong():
    env = os.environ.copy()
    env["P_VALUE"] = str(get_current_p_value())

    subprocess.run(
        [
            "docker", "compose", "-f", "docker-compose.test.yml",
            "up", "-d", "--build", "--force-recreate", "kong"
        ],
        cwd=ROOT,
        check=True,
        env=env,
    )
    wait_for_service(f"{API_URL}/users/", timeout=90)
    time.sleep(2)


@pytest.fixture(scope="module", autouse=True)
def restore_original_p_value():
    original = get_current_p_value()
    yield
    set_p_value(original)
    recreate_kong()


def create_user_via_gateway():
    uid = str(uuid.uuid4())[:8]
    payload = {
        "firstName": "Gateway",
        "lastName": "Tester",
        "emails": [f"gateway_{uid}@example.com"],
        "deliveryAddress": {
            "street": "123 Main",
            "city": "Montreal",
            "state": "QC",
            "postalCode": "H3G1M8",
            "country": "Canada"
        }
    }
    r = requests.post(f"{API_URL}/users/", json=payload)
    assert r.status_code == 201
    return r.json()


def create_user_for_order():
    uid = str(uuid.uuid4())[:8]
    payload = {
        "firstName": "Order",
        "lastName": "Tester",
        "emails": [f"order_{uid}@example.com"],
        "deliveryAddress": {
            "street": "123 Test Street",
            "city": "Montreal",
            "state": "QC",
            "postalCode": "H3G1M8",
            "country": "Canada"
        }
    }
    r = requests.post(f"{API_URL}/users/", json=payload)
    assert r.status_code == 201
    return r.json()


def create_order_for_user(user, status="under process"):
    payload = {
        "userId": user["userId"],
        "items": [{"itemId": "item-1", "quantity": 1, "price": 10}],
        "userEmails": user["emails"],
        "deliveryAddress": user["deliveryAddress"],
        "orderStatus": status
    }
    r = requests.post(f"{API_URL}/orders/", json=payload)
    assert r.status_code == 201
    return r.json()


def detect_user_service_version(created_user: dict) -> str:
    # v2 auto-populates createdAt/updatedAt; v1 leaves them null
    if created_user.get("createdAt") is not None or created_user.get("updatedAt") is not None:
        return "v2"
    return "v1"


class TestGatewayWeightedRouting:
    def test_gateway_routes_all_to_v1_when_p_100(self):
        set_p_value(100)
        recreate_kong()

        versions = []
        for _ in range(6):
            user = create_user_via_gateway()
            versions.append(detect_user_service_version(user))

        assert all(v == "v1" for v in versions)

    def test_gateway_routes_all_to_v2_when_p_0(self):
        set_p_value(0)
        recreate_kong()

        versions = []
        for _ in range(6):
            user = create_user_via_gateway()
            versions.append(detect_user_service_version(user))

        assert all(v == "v2" for v in versions)

    def test_gateway_splits_between_v1_and_v2_when_p_50(self):
        set_p_value(50)
        recreate_kong()

        versions = []
        for _ in range(20):
            user = create_user_via_gateway()
            versions.append(detect_user_service_version(user))

        assert "v1" in versions
        assert "v2" in versions


class TestOrderApiExtensions:
    def test_get_orders_by_state(self):
        user = create_user_for_order()
        order = create_order_for_user(user, status="under process")

        r = requests.get(f"{API_URL}/orders/", params={"status": "under process"})
        assert r.status_code == 200

        data = r.json()
        assert isinstance(data, list)
        assert any(o["orderId"] == order["orderId"] for o in data)

    def test_update_order_status(self):
        user = create_user_for_order()
        order = create_order_for_user(user, status="under process")

        r = requests.put(
            f"{API_URL}/orders/{order['orderId']}/status",
            json={"orderStatus": "shipping"}
        )
        assert r.status_code == 200

        data = r.json()
        if isinstance(data, list):
            updated = data[1]
        else:
            updated = data

        assert updated["orderStatus"] == "shipping"

    def test_update_order_details(self):
        user = create_user_for_order()
        order = create_order_for_user(user, status="under process")

        new_emails = [f"updated_{uuid.uuid4().hex[:8]}@example.com"]
        new_address = {
            "street": "789 Updated Ave",
            "city": "Laval",
            "state": "QC",
            "postalCode": "H7A1A1",
            "country": "Canada"
        }

        r = requests.put(
            f"{API_URL}/orders/{order['orderId']}/details",
            json={
                "userEmails": new_emails,
                "deliveryAddress": new_address
            }
        )
        assert r.status_code == 200

        data = r.json()
        if isinstance(data, list):
            updated = data[1]
        else:
            updated = data

        assert updated["userEmails"] == new_emails
        assert updated["deliveryAddress"] == new_address

    def test_order_creation_rejects_invalid_status(self):
        user = create_user_for_order()

        payload = {
            "userId": user["userId"],
            "items": [{"itemId": "item-1", "quantity": 1, "price": 10}],
            "userEmails": user["emails"],
            "deliveryAddress": user["deliveryAddress"],
            "orderStatus": "processing"
        }

        r = requests.post(f"{API_URL}/orders/", json=payload)
        assert r.status_code == 400

    def test_order_creation_rejects_unknown_user(self):
        payload = {
            "userId": "missing-user-id",
            "items": [{"itemId": "item-1", "quantity": 1, "price": 10}],
            "userEmails": ["missing@example.com"],
            "deliveryAddress": {
                "street": "123 Main",
                "city": "Montreal",
                "state": "QC",
                "postalCode": "H3G1M8",
                "country": "Canada"
            },
            "orderStatus": "under process"
        }

        r = requests.post(f"{API_URL}/orders/", json=payload)
        assert r.status_code in [400, 404]