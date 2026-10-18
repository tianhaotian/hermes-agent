"""Bot RPCs keep their profile context and refusal contract inside a CLI loop (#141087)."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from websockets.sync.server import serve

from agent.memory_provider import spawn_context_thread
from hermes_cli import gateway_client, gateway_runtime
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override
from tools import bot_live_delivery


@pytest.fixture
def authority_peer(tmp_path, monkeypatch):
    received = []

    def handle(ws):
        frame = json.loads(ws.recv())
        received.append(frame)
        outcome = (
            {"error": {"code": -32000, "message": "held_by_session_writer", "data": {"admitted": False}}}
            if frame["params"]["message"] == "refuse"
            else {"result": {"status": "queued", "delivery_id": frame["params"]["id"]}}
        )
        ws.send(json.dumps({"jsonrpc": "2.0", "id": frame["id"], **outcome}))

    with serve(handle, "127.0.0.1", 0, subprotocols=[gateway_client.GATEWAY_WS_PROTOCOL]) as server:
        thread = spawn_context_thread(target=server.serve_forever, name="test-bot-authority")
        thread.start()
        endpoint = SimpleNamespace(api_origin=f"http://127.0.0.1:{server.socket.getsockname()[1]}")
        recipient = tmp_path / "profiles" / "recipient"
        sender = tmp_path / "profiles" / "sender"

        def discover(home, timeout):
            assert home == recipient
            assert get_hermes_home() == sender
            return SimpleNamespace(state="ready", endpoint=endpoint)

        def ticket(home, target):
            assert home == recipient and target is endpoint
            assert get_hermes_home() == sender
            return "synthetic-ticket"

        monkeypatch.setattr(gateway_runtime, "discover_gateway_endpoint", discover)
        monkeypatch.setattr(gateway_client, "_session_ticket", ticket)
        token = set_hermes_home_override(sender)
        try:
            yield recipient, received
        finally:
            reset_hermes_home_override(token)
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


@pytest.mark.parametrize("running_loop", [False, True])
@pytest.mark.parametrize("operation", ["deliver", "settle"])
def test_authority_rpc_preserves_context_and_typed_refusals(authority_peer, running_loop, operation):
    home, received = authority_peer
    call = getattr(bot_live_delivery, f"authority_{'delivery' if operation == 'deliver' else 'settle'}")
    params = {"id": "a" * 32, "profile": "recipient", "message": "hello"}

    def exercise():
        assert call(home, params) == {"status": "queued", "delivery_id": params["id"]}
        with pytest.raises(gateway_client.GatewayRPCError, match="held_by_session_writer") as error:
            call(home, {**params, "message": "refuse"})
        assert error.value.code == -32000 and error.value.data == {"admitted": False}

    async def inside_loop():
        exercise()

    if running_loop:
        asyncio.run(inside_loop())
    else:
        exercise()
    assert [frame["method"] for frame in received] == [f"bot_relay.{operation}"] * 2
    assert received[0]["params"] == params
