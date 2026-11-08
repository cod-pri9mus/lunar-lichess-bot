from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from lichess_vision_bot.webui import BotState, WebServer


def test_state_commands_and_snapshot():
    state = BotState({"engine": "Stockfish 17.1"})
    state.update(status="waiting", message="Ожидание стартовой позиции")
    state.command("toggle-pause")
    assert state.drain_commands() == ["toggle-pause"]
    snapshot = state.snapshot()
    assert snapshot["status"] == "waiting"
    assert snapshot["message"] == "Ожидание стартовой позиции"
    assert snapshot["config"]["engine"] == "Stockfish 17.1"
    assert snapshot["paused"] is False
    assert snapshot["games"] == 0


def test_frame_sequence_increments():
    state = BotState()
    assert state.frame() is None
    state.set_frame(b"\xff\xd8fake-jpeg")
    assert state.frame() == b"\xff\xd8fake-jpeg"
    state.set_frame(b"\xff\xd8second")
    assert state.snapshot()["frame_seq"] == 2


@pytest.fixture()
def server():
    state = BotState({"engine": "Stockfish 17.1"})
    state.update(status="waiting", message="Ожидание")
    instance = WebServer(state, "127.0.0.1", 0)
    url = instance.start()
    assert url is not None
    try:
        yield url, state
    finally:
        instance.stop()


def _request(url: str, *, method="GET", data=None, headers=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    return urllib.request.urlopen(request, timeout=5)


def test_http_state_and_html(server):
    url, _state = server
    with _request(url + "api/state") as response:
        payload = json.load(response)
    assert payload["status"] == "waiting"

    with _request(url) as response:
        html = response.read().decode("utf-8")
    assert "LUNAR" in html
    assert "Вкладка Lichess" in html
    assert "simBoard" in html


def test_http_command(server):
    url, state = server
    body = json.dumps({"command": "toggle-pause"}).encode("utf-8")
    with _request(
        url + "api/command",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    ) as response:
        assert json.load(response)["ok"] is True
    assert state.drain_commands() == ["toggle-pause"]


def test_dom_roundtrip():
    state = BotState()
    assert state.dom() is None
    payload = {
        "fen": "8/8/8/8/8/8/8/K6k w - - 0 1",
        "turn": "white",
        "orientation": "white",
        "color": "white",
        "rect": {"x": 10, "y": 20, "width": 640, "height": 640},
    }
    state.set_dom(payload)
    dom = state.dom()
    assert dom is not None
    assert dom["payload"]["fen"] == payload["fen"]
    assert dom["payload"]["turn"] == "white"
    assert dom["at"] > 0


def test_http_dom(server):
    url, state = server
    payload = {
        "fen": "8/8/8/8/8/8/8/K6k b - - 0 1",
        "turn": "black",
        "orientation": "black",
        "color": "black",
        "rect": {"x": 10, "y": 20, "width": 640, "height": 640},
    }
    body = json.dumps(payload).encode("utf-8")
    with _request(
        url + "api/dom",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    ) as response:
        assert json.load(response)["ok"] is True
    dom = state.dom()
    assert dom is not None
    assert dom["payload"]["turn"] == "black"


def test_http_rejects_unknown_command(server):
    url, _state = server
    body = json.dumps({"command": "shutdown-machine"}).encode("utf-8")
    with pytest.raises(urllib.error.HTTPError) as info:
        _request(
            url + "api/command",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        )
    assert info.value.code == 400


def test_cors_allows_lichess_and_extension(server):
    url, _state = server
    with _request(url + "api/state", headers={"Origin": "https://lichess.org"}) as response:
        assert response.headers.get("Access-Control-Allow-Origin") == "https://lichess.org"

    body = json.dumps({"command": "redetect"}).encode("utf-8")
    with _request(
        url + "api/command",
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Origin": "chrome-extension://abcdefghijklmnop",
        },
    ) as response:
        assert json.load(response)["ok"] is True

    body = json.dumps({"command": "redetect"}).encode("utf-8")
    with _request(
        url + "api/command",
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Origin": "moz-extension://abcdefghijklmnop",
        },
    ) as response:
        assert json.load(response)["ok"] is True


def test_cors_rejects_foreign_origin(server):
    url, _state = server
    body = json.dumps({"command": "stop"}).encode("utf-8")
    with pytest.raises(urllib.error.HTTPError) as info:
        _request(
            url + "api/command",
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
            },
        )
    assert info.value.code == 403


def test_start_fen_request(server):
    url, state = server
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    body = json.dumps(
        {"command": "start-fen", "fen": fen, "color": "white", "flipped": False}
    ).encode("utf-8")
    with _request(
        url + "api/command",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    ) as response:
        assert json.load(response)["ok"] is True
    requests = state.drain_start_requests()
    assert requests == [{"fen": fen, "color": "white", "flipped": False}]


def test_start_fen_rejects_bad_color(server):
    url, _state = server
    body = json.dumps(
        {"command": "start-fen", "fen": "8/8/8/8/8/8/8/K6k w - - 0 1", "color": "green"}
    ).encode("utf-8")
    with pytest.raises(urllib.error.HTTPError) as info:
        _request(
            url + "api/command",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        )
    assert info.value.code == 400


def test_start_current_request(server):
    url, state = server
    body = json.dumps(
        {
            "command": "start-current",
            "color": "black",
            "flipped": True,
            "my_turn": False,
        }
    ).encode("utf-8")
    with _request(
        url + "api/command",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    ) as response:
        assert json.load(response)["ok"] is True
    assert state.drain_start_current_requests() == [
        {"color": "black", "flipped": True, "my_turn": False}
    ]


def test_set_elo_command(server):
    url, state = server
    body = json.dumps({"command": "set-elo", "elo": 2000}).encode("utf-8")
    with _request(
        url + "api/command",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    ) as response:
        assert json.load(response)["ok"] is True
    assert state.drain_commands() == ["set-elo:2000"]


def test_set_elo_rejects_out_of_range(server):
    url, _state = server
    body = json.dumps({"command": "set-elo", "elo": 900}).encode("utf-8")
    with pytest.raises(urllib.error.HTTPError) as info:
        _request(
            url + "api/command",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        )
    assert info.value.code == 400
