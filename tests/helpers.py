import time
import typing as t
import requests

def poll_task_result(
    session: requests.Session,
    base_url: str,
    task_id: str,
    *,
    timeout: float = 20.0,
    interval: float = 0.5,
) -> t.Dict[str, t.Any]:
    url = f"{base_url}/search/tasks/{task_id}"
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = session.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        last = data
        if data.get("status") in ("SUCCESS", "FAILURE"):
            return data
        time.sleep(interval)
    return last or {"status": "TIMEOUT", "task_id": task_id}
