import pytest
import requests
import os
import time
import uuid
import copy
from pymongo import MongoClient
from pymongo import AsyncMongoClient
from dotenv import load_dotenv
# Initializing environment variables
API_url = os.getenv("API_url", "http://localhost:8000")
MongoURI = os.getenv(
    "MongoURI",
    "mongodb://admin:password@localhost:27017/"
)
DBname = os.getenv("DATABASE_NAME", "aware_microservices")

# Waitng for the API Gateway to be ready before running tests
def wait_for_service(url, timeout=30):
    for _ in range(timeout):
        try:
            r = requests.get(url)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1)
    raise Exception(f"Service not ready: {url}")


@pytest.fixture(scope="session", autouse=True)
def wait_for_system():
    wait_for_service(f"{API_url}/users/")
    time.sleep(2)

# Ensures that the MongoB client is properly closed after tests
@pytest.fixture
def mongo():
    c = MongoClient(MongoURI)
    yield c[DBname]
    c.close()


@pytest.fixture
def test_user(): # Create test user
    uid = str(uuid.uuid4())[:8]
    return {
        "firstName": "George",
        "lastName": "Nashed",
        "emails": [f"test_{uid}@gmail.com"],
        "deliveryAddress": {
            "street": "123 Main",
            "city": "Montreal",
            "state": "QC",
            "postalCode": "H3G1M8",
            "country": "Canada"
        }
    }

class TestUsrs:
#Creating a user and ensuring they are in the DB
    def test_create_user(self, test_user):
        r = requests.post(f"{API_url}/users/", json=test_user)
        assert r.status_code == 201
        dt = r.json()
        assert "userId" in dt
        assert dt["userId"]
# Retrieving the user
    def test_get_user(self, test_user):
        r = requests.post(f"{API_url}/users/", json=test_user)
        assert r.status_code == 201
        UserID = r.json()["userId"]

        r = requests.get(f"{API_url}/users/{UserID}")
        assert r.status_code == 200

        dt = r.json()
        assert dt["firstName"] == test_user["firstName"]
        assert dt["emails"] == test_user["emails"]
#test that the user is in DB
    def test_user_persisted_in_mongo(self, test_user, mongo):
        r = requests.post(f"{API_url}/users/", json=test_user)
        assert r.status_code == 201
        UserID = r.json()["userId"]

        time.sleep(1)
        
        db_user = mongo.users.find_one({"userId": UserID})
        assert db_user is not None
        assert db_user["emails"] == test_user["emails"]
#Testing an Invalid usr
    @pytest.mark.parametrize("case", ["missing_street", "duplicate_email"])
    def test_invalid_user_cases(self, test_user, case):
        payload = copy.deepcopy(test_user)

        if case == "missing_street":
            payload["deliveryAddress"].pop("street")
            r = requests.post(f"{API_url}/users/", json=payload)
            assert r.status_code == 400

        elif case == "duplicate_email":
            
            r1 = requests.post(f"{API_url}/users/", json=payload)
            assert r1.status_code == 201
            
            r2 = requests.post(f"{API_url}/users/", json=payload)
            assert r2.status_code in [400, 409]


class Testorders:

    def create_user(self):
        uid = str(uuid.uuid4())[:8]
        payload = {
            "firstName": "Test",
            "lastName": "User",
            "emails": [f"{uid}@test.com"],
            "deliveryAddress": {
                "street": "123 St",
                "city": "City",
                "state": "ST",
                "postalCode": "12345",
                "country": "CA"
            }
        }
        r = requests.post(f"{API_url}/users/", json=payload)
        assert r.status_code == 201
        return r.json()
#Testing creating an order
    def test_create_order(self):
        user = self.create_user()

        order = {
            "userId": user["userId"],
            "items": [{"itemId": "x", "quantity": 1, "price": 10}],
            "userEmails": user["emails"],
            "deliveryAddress": user["deliveryAddress"],
            "orderStatus": "processing"
        }

        r = requests.post(f"{API_url}/orders/", json=order)
        assert r.status_code == 201
        dt = r.json()
        assert "orderId" in dt
        assert dt["orderId"]

    def test_order_contains_user_reference(self):
        # TODO: Implement test for order containing user reference
        pass
#Ensuring the order is in DB
    def test_order_persisted_in_mongo(self, mongo):
        user = self.create_user()

        order = {
            "userId": user["userId"],
            "items": [{"itemId": "x", "quantity": 1, "price": 10}],
            "userEmails": user["emails"],
            "deliveryAddress": user["deliveryAddress"],
            "orderStatus": "processing"
        }

        r = requests.post(f"{API_url}/orders/", json=order)
        assert r.status_code == 201
        order_id = r.json()["orderId"]

        time.sleep(1)
        
        db_order = mongo.orders.find_one({"orderId": order_id})
        assert db_order is not None
        assert db_order["userId"] == user["userId"]
#Testing orders with invalid user
    def test_order_with_invalid_user(self):
        order = {
            "userId": "fakeusr",
            "items": [{"itemId": "x", "quantity": 1, "price": 10}],
            "userEmails": ["fake@test.com"],
            "deliveryAddress": {},
            "orderStatus": "processing"
        }

        r = requests.post(f"{API_url}/orders/", json=order)
        assert r.status_code in [400, 404]


class Testeventflow:

    def test_user_update_propagates(self):
        # TODO: Implement test for user update propagation
        pass


class Testgateway:

    def test_gateway_health(self):
        r = requests.get(f"{API_url}/users/")
        assert r.status_code == 200

    def test_multi_requests(self):
        responses = []
        for i in range(10):
            r = requests.get(f"{API_url}/users/")
            responses.append(r)
            time.sleep(0.1)

        for r in responses:
            assert r.status_code == 200
            dt = r.json()
            assert isinstance(dt, list)