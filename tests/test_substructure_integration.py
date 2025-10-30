import pytest
import json
import requests
from helpers import poll_task_result

SEED = [

  {"id": "XCompound_01", "smiles": "C1=CC(=CC=C1C(=O)O)N(CC)CCCCCCCCCCCCCCCC"},
  {"id": "XCompound_02", "smiles": "CCN(CC)CCOC(=O)C1=CC=CC=C1CCCCCCCCCCCCCC"},
  {"id": "XCompound_03", "smiles": "O=C(O)C1=CC=CC(=C1)C(CN)CCOCCCCCCCCCCCCC"},
  {"id": "XCompound_04", "smiles": "C1CCN(CC1)CCOC(=O)C2=CC=CC=C2CCCCCCCCCCC"},
  {"id": "XCompound_05", "smiles": "CC(C)NCC(O)C(=O)OCC1=CC=CC=C1CCCCCCCCCCC"},
  {"id": "XCompound_06", "smiles": "CNC(=O)C1=CC=CC=C1CCN(CC)CCCCCCCCCCCCCCC"},
  {"id": "XCompound_07", "smiles": "O=C(OC)C1=CC=CC=C1C(C)NCCOCCCCCCCCCCCCCC"},
  {"id": "XCompound_08", "smiles": "C1=CC=C(C=C1)C(=O)OCCN(CC)CCOCCCCCCCCCCC"},
  {"id": "XCompound_09", "smiles": "CCOC(=O)C1=CC=CC=C1C(N)CCOCCNCCCCCCCCCCC"},
  {"id": "XCompound_10", "smiles": "C1CCOC1C(=O)NCCOCCN(CC)CCCCCCCCCCCCCCCCC"}

]

SUBSTRUCTURE = "CCCCCCCCCCCCCC"


def test_00_seed_data(wait_for_api, session, base_url):
    for m in SEED:
        r = session.post(f"{base_url}/add", json=m, timeout=10)
        assert r.status_code in (200, 201), f"/add failed for {m['id']}: {r.status_code} {r.text}"


def test_01_duplicate_creation_returns_400(session, base_url):
    ids = [SEED[0]["id"], SEED[1]["id"]]
    for mol in SEED[:2]:
        session.post(f"{base_url}/add", json=mol, timeout=10)  # результат не критичен

    for mol in SEED[:2]:
        r = session.post(f"{base_url}/add", json=mol, timeout=10)
        assert r.status_code == 400, f"Expected 400 for duplicate {mol['id']}, got {r.status_code} {r.text}"


def test_02_first_post_returns_pending_and_not_cached(session: requests.Session, base_url: str):
    r = session.post(f"{base_url}/search/tasks", params={"query": SUBSTRUCTURE}, timeout=10)
    r.raise_for_status()
    j = r.json()

    assert "task_id" in j and isinstance(j["task_id"], str) and j["task_id"], f"bad task_id: {j}"
    assert j.get("status") == "PENDING", f"expected PENDING, got: {j}"
    assert j.get("cached") is False, f"expected cached=false, got: {j}"

    pytest.task_id_for_long_chain = j["task_id"]


def test_03_poll_get_until_success_and_validate_hits(session: requests.Session, base_url: str):
    task_id = getattr(pytest, "task_id_for_long_chain", None)
    assert task_id, "missing task id from previous test"

    res = poll_task_result(session, base_url, task_id, timeout=40.0, interval=0.5)
    assert res["status"] == "SUCCESS", f"Unexpected status: {res}"

    result = res.get("result", {})
    hits = {m["id"] for m in result.get("matches", [])}

    expected_any = {"XCompound_01", "XCompound_02", "XCompound_06", "XCompound_10"}
    assert hits & expected_any, f"expected any of {expected_any}, got {hits}"


def test_04_second_post_returns_cached_success_immediately(session: requests.Session, base_url: str):
    r = session.post(f"{base_url}/search/tasks", params={"query": SUBSTRUCTURE}, timeout=10)
    r.raise_for_status()
    j = r.json()

    assert j.get("cached") is True, f"expected cached=true, got: {j}"
    assert j.get("status") == "SUCCESS", f"expected immediate SUCCESS, got: {j}"

    hits = {m["id"] for m in j.get("result", {}).get("matches", [])}
    expected_any = {"XCompound_01", "XCompound_02", "XCompound_06", "XCompound_10"}
    assert hits & expected_any, f"expected any of {expected_any}, got {hits}"

def test_05_invalid_query_yields_failure(session: requests.Session, base_url: str):
    r = session.post(f"{base_url}/search/tasks", params={"query": "[*INVALID*"}, timeout=10)
    r.raise_for_status()
    task_id = r.json()["task_id"]
    res = poll_task_result(session, base_url, task_id, timeout=10.0)
    assert res["status"] == "FAILURE", f"Unexpected: {res}"
    assert "error" in res

def test_06_draw_existing_xcompound(session, base_url):
    mol_id = "XCompound_01"
    r = session.get(f"{base_url}/draw/{mol_id}", params={"fmt": "png", "size": 300}, timeout=10)
    assert r.status_code == 200, f"Unexpected status {r.status_code}: {r.text}"
    assert r.headers.get("content-type") == "image/png"
    assert r.content.startswith(b"\x89PNG\r\n\x1a\n"), "Ответ не выглядит как PNG"
    assert len(r.content) > 1000, "слишком маленький PNG (возможно пустой)"


def test_07_patch_update_existing(session, base_url, wait_for_api):
    
    mol_id = "XCompound_02"
    new_smiles = "CCN(CC)CCOC(=O)C1=CC=CC=C1CCCCCCCCCCCCCN"
    r = session.get(f"{base_url}/molecule/{mol_id}", timeout=10)
    assert r.status_code == 200, f"GET /molecule/{mol_id} failed: {r.text}"
    original = r.json()
    original_smiles = original["smiles"]
    
    r = session.patch(
        f"{base_url}/patch/{mol_id}",
        json={"smiles": new_smiles},
        timeout=10,
    )
    assert r.status_code == 200, f"PUT /patch/{mol_id} failed: {r.text}"
    updated = r.json()
    assert updated["id"] == mol_id
    r = session.get(f"{base_url}/molecule/{mol_id}", timeout=10)
    assert r.status_code == 200, f"GET /molecule/{mol_id} after update failed: {r.text}"
    after = r.json()
    after_smiles = after["smiles"]

    assert after_smiles != original_smiles, (
        f"SMILES did not change: before={original_smiles}, after={after_smiles}"
    )



def test_08_delete_all_seeded(session, base_url):

    for m in SEED:
        r = session.delete(f"{base_url}/delete/{m['id']}", timeout=10)
        assert r.status_code == 204, f"DELETE failed for {m['id']}: {r.status_code} {r.text}"
