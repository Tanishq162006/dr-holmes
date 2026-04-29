"""Phase 4 API integration tests.

Spins up the FastAPI server in a subprocess (more realistic than in-process
ASGI testing for an asyncio-heavy stack) and exercises:
  - REST endpoints
  - Mock-mode case runs end-to-end
  - WebSocket replay from Postgres audit log
  - Health/readiness checks

Requires no LLM API keys — uses mock fixtures throughout.
"""
import asyncio
import json
import os
import subprocess
import time
from collections import Counter
from pathlib import Path
import socket

import pytest
import pytest_asyncio
import httpx
import websockets


PROJECT_ROOT = Path(__file__).parent.parent
FIXTURE = PROJECT_ROOT / "fixtures" / "case_01_easy_mi.json"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """Boot uvicorn in a subprocess on an ephemeral port. Tear down at end."""
    port = _free_port()
    db_path = PROJECT_ROOT / "data" / f"test_cases_{port}.db"
    if db_path.exists():
        db_path.unlink()

    env = {
        **os.environ,
        "DR_HOLMES_AUTH_MODE": "dev",
        "DATABASE_URL": "",  # → SQLite fallback
        # use a unique sqlite file per test session by changing CWD-relative path
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        ["python3", "-m", "uvicorn", "dr_holmes.api.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Wait for liveness
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            with httpx.Client() as c:
                r = c.get(f"{base_url}/healthz", timeout=0.5)
                if r.status_code == 200:
                    break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("Server didn't come up")

    yield base_url, port

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_healthz(server):
    base_url, _ = server
    r = httpx.get(f"{base_url}/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz(server):
    base_url, _ = server
    r = httpx.get(f"{base_url}/readyz")
    assert r.status_code == 200
    body = r.json()
    assert "components" in body
    assert "database" in body["components"]


def test_list_agents(server):
    base_url, _ = server
    r = httpx.get(f"{base_url}/api/agents")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert names == {"Hauser", "Forman", "Carmen", "Chen", "Wills", "Caddick"}


def test_agent_profile(server):
    base_url, _ = server
    r = httpx.get(f"{base_url}/api/agents/Hauser/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["bias"] == "rare"
    assert body["specialty"] == "Lead diagnostician"


def test_agent_profile_404(server):
    base_url, _ = server
    r = httpx.get(f"{base_url}/api/agents/Quincy/profile")
    assert r.status_code == 404


def test_metrics(server):
    base_url, _ = server
    r = httpx.get(f"{base_url}/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text


def _create_case(base_url: str) -> str:
    body = {
        "patient_presentation": json.loads(FIXTURE.read_text())["patient_presentation"],
        "mock_mode": True,
        "fixture_path": str(FIXTURE),
    }
    r = httpx.post(f"{base_url}/api/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wait_concluded(base_url: str, case_id: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = httpx.get(f"{base_url}/api/cases/{case_id}")
        if r.status_code == 200 and r.json()["status"] == "concluded":
            return r.json()
        time.sleep(0.25)
    raise AssertionError(f"Case {case_id} did not conclude within {timeout}s")


def test_create_mock_case_runs_to_completion(server):
    base_url, _ = server
    case_id = _create_case(base_url)
    detail = _wait_concluded(base_url, case_id)
    assert detail["final_report"] is not None
    assert "stemi" in detail["final_report"]["consensus_dx"].lower()
    assert detail["convergence_reason"] == "team_agreement"


def test_transcript_has_full_event_stream(server):
    base_url, _ = server
    case_id = _create_case(base_url)
    _wait_concluded(base_url, case_id)
    transcript = httpx.get(f"{base_url}/api/cases/{case_id}/transcript").json()
    types = Counter(e["event_type"] for e in transcript)
    # At minimum these event types must appear
    assert "case_started" in types
    assert "agent_response" in types
    assert "bayesian_update" in types
    assert "caddick_routing" in types
    assert "case_converged" in types
    assert "final_report" in types
    # Sequence numbers must be monotonic and unique
    seqs = [e["sequence"] for e in transcript]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_differentials_endpoint(server):
    base_url, _ = server
    case_id = _create_case(base_url)
    _wait_concluded(base_url, case_id)
    r = httpx.get(f"{base_url}/api/cases/{case_id}/differentials")
    assert r.status_code == 200
    body = r.json()
    assert "top_dx" in body
    assert "top_prob" in body


def test_report_endpoint(server):
    base_url, _ = server
    case_id = _create_case(base_url)
    _wait_concluded(base_url, case_id)
    r = httpx.get(f"{base_url}/api/cases/{case_id}/report")
    assert r.status_code == 200
    body = r.json()
    assert body["consensus_dx"]
    assert body["confidence"] > 0


def test_list_cases(server):
    base_url, _ = server
    _create_case(base_url)
    r = httpx.get(f"{base_url}/api/cases")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_404_on_unknown_case(server):
    base_url, _ = server
    r = httpx.get(f"{base_url}/api/cases/does_not_exist")
    assert r.status_code == 404


# ── WebSocket tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_replay(server):
    base_url, port = server
    case_id = _create_case(base_url)
    # let case finish
    _wait_concluded(base_url, case_id)

    ws_url = f"ws://127.0.0.1:{port}/ws/cases/{case_id}?replay=true"
    events = []
    async with websockets.connect(ws_url) as ws:
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                data = json.loads(msg)
                events.append(data)
                if data.get("type") == "replay_complete":
                    break
        except asyncio.TimeoutError:
            pass

    assert len(events) > 5, f"Got only {len(events)} events"
    types = [e.get("event_type") or e.get("type") for e in events]
    assert "handshake" in types
    assert "case_started" in types
    assert "final_report" in types
    assert "replay_complete" in types


@pytest.mark.asyncio
async def test_websocket_live_stream(server):
    base_url, port = server
    case_id_holder: dict = {}

    async def consumer():
        while "id" not in case_id_holder:
            await asyncio.sleep(0.05)
        case_id = case_id_holder["id"]
        events = []
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/cases/{case_id}") as ws:
            deadline = asyncio.get_event_loop().time() + 8
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    events.append(data)
                    if data.get("event_type") == "final_report":
                        break
                except asyncio.TimeoutError:
                    pass
        return events

    async def producer():
        await asyncio.sleep(0.1)  # let consumer connect
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{base_url}/api/cases", json={
                "patient_presentation": json.loads(FIXTURE.read_text())["patient_presentation"],
                "mock_mode": True,
                "fixture_path": str(FIXTURE),
            })
            case_id_holder["id"] = r.json()["id"]

    consumer_task = asyncio.create_task(consumer())
    await producer()
    events = await consumer_task

    types = {e.get("event_type") or e.get("type") for e in events}
    assert "handshake" in types
    # Either we got the live stream, or replay caught us up
    assert ("case_started" in types) or ("agent_response" in types) or ("final_report" in types)
