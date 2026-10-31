"""webterm.server モジュールのユニットテスト。"""

from __future__ import annotations

import asyncio
import webbrowser

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from webterm.config import AppConfig
from webterm.pty_backend import PtyBackend
from webterm.server import create_app


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

    app = create_app(AppConfig(open_browser=False))
    with TestClient(app) as client:
        response = client.get("/")
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

    config = AppConfig(host="127.0.0.1", port=8888, open_browser=True)
    app = create_app(config)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200

    assert opened_urls == ["http://127.0.0.1:8888"]


def test_index_endpoint_returns_html() -> None:
    """ルートエンドポイント (GET /) が HTML を返すことを検証する。"""
    app = create_app()
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "xterm.min.js" in response.text
    assert 'const ACTIVE_THEME_NAME = "dark";' in response.text


def test_index_endpoint_applies_custom_theme() -> None:
    """指定されたカラーテーマ名が HTML に反映されることを検証する。"""
    app = create_app(AppConfig(theme="dracula"))
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert 'const ACTIVE_THEME_NAME = "dracula";' in response.text


def test_websocket_endpoint_communication() -> None:
    """WebSocket エンドポイント (/ws) の入出力とリサイズを検証する。"""
    created_backends: list[FakePtyBackend] = []

    def fake_factory(command: list[str]) -> PtyBackend:
        backend = FakePtyBackend(command)
        created_backends.append(backend)
        return backend

    config = AppConfig(command=["test-shell"])
    app = create_app(config=config, pty_factory=fake_factory)
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
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
        client.websocket_connect("/ws") as websocket,
    ):
        websocket.receive_text()

    assert len(created_backends) == 1
    assert created_backends[0].closed is True
