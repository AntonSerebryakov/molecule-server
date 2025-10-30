import os
import time
import requests
import pytest

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")

POLL_INTERVAL = float(os.getenv("TEST_POLL_INTERVAL", "0.5"))
POLL_TIMEOUT = float(os.getenv("TEST_POLL_TIMEOUT", "20.0"))

@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL

@pytest.fixture(scope="session")
def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s

@pytest.fixture(scope="session")
def wait_for_api(base_url: str):
    deadline = time.time() + POLL_TIMEOUT
    url = f"{base_url}/docs"
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=3)
            if r.status_code < 500:
                break
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)
