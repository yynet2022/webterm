"""webterm.server モジュールのユニットテスト。"""

from __future__ import annotations

import asyncio
import socket
import webbrowser
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

import webterm.server
from webterm.config import AppConfig
from webterm.pty_backend import PtyBackend
from webterm.server import create_app, get_local_ip_addresses


class FakePtyBackend:
    """テスト用のモック PTY バックエンド。"""

    def __init__(
        self,
        command: list[str],
        *,
        raise_on_read: bool = False,
    ) -> None:
        """モックバックエンドを初期化する。

        Args:
            command: 起動コマンドのリスト。
            raise_on_read: read 呼び出し時に例外を送出するかどうか。
        """
        self.command = command
        self.raise_on_read = raise_on_read
        self.written_data: list[str] = []
        self.resized_dimensions: list[tuple[int, int]] = []
        self.closed: bool = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._queue.put_nowait("hello from pty")

    async def read(self) -> str:
        """キューからテスト出力を返すか、設定に応じて例外を送出する。

        Returns:
            str: テスト出力文字列。

        Raises:
            RuntimeError: raise_on_read が True の場合。
        """
        if self.raise_on_read:
            raise RuntimeError("Simulated PTY read error")
        return await self._queue.get()

    def write(self, data: str) -> None:
        """書き込まれたデータを記録し、終了シグナルで EOF を送る。

        Args:
            data: 書き込まれた文字列。
        """
        self.written_data.append(data)
        if data == "exit\n":
            self._queue.put_nowait("")

    def resize(self, rows: int, cols: int) -> None:
        """リサイズ要求を記録する。

        Args:
            rows: 行数。
            cols: 列数。
        """
        self.resized_dimensions.append((rows, cols))

    def close(self) -> None:
        """クローズ状態を記録する。"""
        self.closed = True


def test_lifespan_without_open_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """open_browser が False のときブラウザが開かれないことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    opened_urls: list[str] = []

    def fake_open(url: str) -> bool:
        opened_urls.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)

    config = AppConfig(open_browser=False)
    app = create_app(config)
    with TestClient(app) as client:
        response = client.get(f"/{config.token}")
        assert response.status_code == 200

    assert opened_urls == []


def test_lifespan_with_open_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """open_browser が True のとき起動時にブラウザが開かれることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    opened_urls: list[str] = []

    def fake_open(url: str) -> bool:
        opened_urls.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)

    config = AppConfig(
        host="127.0.0.1",
        port=8888,
        open_browser=True,
        token="test-token-1234",
    )
    app = create_app(config)
    with TestClient(app) as client:
        response = client.get("/test-token-1234")
        assert response.status_code == 200

    assert opened_urls == ["http://127.0.0.1:8888/test-token-1234"]


def test_lifespan_wildcard_host_outputs_lan_ips_and_opens_localhost(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """0.0.0.0 指定時に 127.0.0.1 と LAN IP を出力しブラウザを開くか検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
        capsys: pytest の標準出力・標準エラー出力キャプチャフィクスチャ。
    """
    opened_urls: list[str] = []

    def fake_open(url: str) -> bool:
        opened_urls.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)
    monkeypatch.setattr(
        webterm.server,
        "get_local_ip_addresses",
        lambda: ["192.168.1.10", "10.0.0.5"],
    )

    config = AppConfig(
        command=["cmd.exe"],
        host="0.0.0.0",
        port=8000,
        open_browser=True,
        token="tok-xyz",
    )
    app = create_app(config)
    with TestClient(app) as client:
        response = client.get("/tok-xyz")
        assert response.status_code == 200

    captured = capsys.readouterr()
    assert (
        "Server started at: http://127.0.0.1:8000/tok-xyz (Command: cmd.exe)"
        in captured.out
    )
    assert "and http://192.168.1.10:8000/tok-xyz" in captured.out
    assert "and http://10.0.0.5:8000/tok-xyz" in captured.out
    assert "Press Ctrl+C to stop the server." in captured.out
    assert opened_urls == ["http://127.0.0.1:8000/tok-xyz"]


def test_get_local_ip_addresses_collects_unique_non_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非ループバック IP アドレスが重複なく返されることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """

    class DummyUdpSocket:
        def __enter__(self) -> DummyUdpSocket:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def connect(self, target: tuple[str, int]) -> None:
            pass

        def getsockname(self) -> tuple[str, int]:
            return ("192.168.1.50", 54321)

    def fake_getaddrinfo(
        host: str,
        port: Any,
        family: int = 0,
    ) -> list[tuple[Any, ...]]:
        return [
            (socket.AF_INET, 0, 0, "", ("127.0.0.1", 0)),
            (socket.AF_INET, 0, 0, "", ("192.168.1.50", 0)),
            (socket.AF_INET, 0, 0, "", ("172.16.0.2", 0)),
        ]

    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: DummyUdpSocket()
    )
    monkeypatch.setattr(socket, "gethostname", lambda: "my-pc")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert get_local_ip_addresses() == ["192.168.1.50", "172.16.0.2"]


def test_get_local_ip_addresses_handles_loopback_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UDP プローブが 127.x を返し getaddrinfo が失敗した場合の動作を検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """

    class LoopbackUdpSocket:
        def __enter__(self) -> LoopbackUdpSocket:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def connect(self, target: tuple[str, int]) -> None:
            pass

        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 54321)

    def failing_gethostname() -> str:
        raise OSError("Hostname resolution failed")

    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: LoopbackUdpSocket()
    )
    monkeypatch.setattr(socket, "gethostname", failing_gethostname)

    assert get_local_ip_addresses() == []


def test_index_endpoint_returns_html() -> None:
    """トークン付き URL (GET /{token}) が HTML を返すことを検証する。"""
    config = AppConfig()
    app = create_app(config)
    client = TestClient(app)
    response = client.get(f"/{config.token}")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "xterm.min.js" in response.text
    assert 'const ACTIVE_THEME_NAME = "dark";' in response.text
    assert 'window.addEventListener("beforeunload"' in response.text


def test_index_endpoint_applies_custom_theme() -> None:
    """指定されたカラーテーマ名が HTML に反映されることを検証する。"""
    config = AppConfig(theme="dracula")
    app = create_app(config)
    client = TestClient(app)
    response = client.get(f"/{config.token}")
    assert response.status_code == 200
    assert 'const ACTIVE_THEME_NAME = "dracula";' in response.text


def test_index_endpoint_rejects_invalid_token() -> None:
    """不正なトークンでアクセスした際に 404 Not Found が返ることを検証する。"""
    config = AppConfig(token="valid-token")
    app = create_app(config)
    client = TestClient(app)
    assert client.get("/invalid-token").status_code == 404
    assert client.get("/").status_code == 404


def test_websocket_endpoint_rejects_invalid_token() -> None:
    """不正なトークンで WebSocket 接続した際に切断されることを検証する。"""
    created_backends: list[FakePtyBackend] = []

    def fake_factory(command: list[str]) -> PtyBackend:
        backend = FakePtyBackend(command)
        created_backends.append(backend)
        return backend

    config = AppConfig(command=["test-shell"], token="valid-token")
    app = create_app(config=config, pty_factory=fake_factory)
    client = TestClient(app)

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/invalid-token/ws"),
    ):
        pass

    assert created_backends == []


def test_websocket_endpoint_communication() -> None:
    """WebSocket エンドポイント (/{token}/ws) の入出力とリサイズを検証する。"""
    created_backends: list[FakePtyBackend] = []

    def fake_factory(command: list[str]) -> PtyBackend:
        backend = FakePtyBackend(command)
        created_backends.append(backend)
        return backend

    config = AppConfig(command=["test-shell"])
    app = create_app(config=config, pty_factory=fake_factory)
    client = TestClient(app)

    with client.websocket_connect(f"/{config.token}/ws") as websocket:
        output = websocket.receive_text()
        assert output == "hello from pty"

        websocket.send_json({"type": "resize", "rows": 40, "cols": 120})
        websocket.send_json({"type": "unknown"})
        websocket.send_json({"type": "input", "data": "exit\n"})

    assert len(created_backends) == 1
    backend = created_backends[0]
    assert backend.command == ["test-shell"]
    assert backend.resized_dimensions == [(40, 120)]
    assert backend.written_data == ["exit\n"]
    assert backend.closed is True


def test_websocket_pty_read_exception() -> None:
    """PTY の read で例外が発生した際に安全に終了することを検証する。"""
    created_backends: list[FakePtyBackend] = []

    def failing_factory(command: list[str]) -> PtyBackend:
        backend = FakePtyBackend(command, raise_on_read=True)
        created_backends.append(backend)
        return backend

    config = AppConfig(command=["test-shell"])
    app = create_app(config=config, pty_factory=failing_factory)
    client = TestClient(app)

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/{config.token}/ws") as websocket,
    ):
        websocket.receive_text()

    assert len(created_backends) == 1
    assert created_backends[0].closed is True


def test_websocket_once_mode_triggers_on_exit() -> None:
    """Once モード時にセッション終了で on_exit が呼ばれることを検証する。"""
    exit_called: list[bool] = []

    def fake_factory(command: list[str]) -> PtyBackend:
        return FakePtyBackend(command)

    config = AppConfig(command=["test-shell"], once=True)
    app = create_app(
        config=config,
        pty_factory=fake_factory,
        on_exit=lambda: exit_called.append(True),
    )
    client = TestClient(app)

    with client.websocket_connect(f"/{config.token}/ws") as websocket:
        assert websocket.receive_text() == "hello from pty"
        websocket.send_json({"type": "input", "data": "exit\n"})

    assert exit_called == [True]


def test_websocket_once_mode_waits_for_all_sessions() -> None:
    """Once モードで複数接続時は最後の接続が閉じるまで終了しないことを検証。"""
    exit_called: list[bool] = []

    def fake_factory(command: list[str]) -> PtyBackend:
        return FakePtyBackend(command)

    config = AppConfig(command=["test-shell"], once=True)
    app = create_app(
        config=config,
        pty_factory=fake_factory,
        on_exit=lambda: exit_called.append(True),
    )
    client = TestClient(app)

    with client.websocket_connect(f"/{config.token}/ws") as ws1:
        assert ws1.receive_text() == "hello from pty"

        with client.websocket_connect(f"/{config.token}/ws") as ws2:
            assert ws2.receive_text() == "hello from pty"
            ws2.send_json({"type": "input", "data": "exit\n"})

        assert exit_called == []
        ws1.send_json({"type": "input", "data": "exit\n"})

    assert exit_called == [True]
