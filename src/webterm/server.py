"""FastAPI アプリおよび WebSocket ルーティングを提供するモジュール。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import webbrowser
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from webterm.config import AppConfig
from webterm.pty_backend import PtyBackend, create_pty

STATIC_DIR: Path = Path(__file__).resolve().parent / "static"
INDEX_HTML_PATH: Path = STATIC_DIR / "index.html"
THEME_PLACEHOLDER: str = "__THEME__"
DEFAULT_ROWS: int = 24
DEFAULT_COLS: int = 80


def load_index_html(theme: str = "dark") -> str:
    """フロントエンド用の HTML ファイルを読み込み、テーマ名を埋め込んで返す。

    Args:
        theme: 適用するカラーテーマ名。

    Returns:
        str: テーマ設定反映済みの index.html 文字列内容。
    """
    raw_html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    return raw_html.replace(THEME_PLACEHOLDER, theme)


def create_app(
    config: AppConfig | None = None,
    pty_factory: Callable[[list[str]], PtyBackend] = create_pty,
) -> FastAPI:
    """設定に基づいて FastAPI アプリケーションインスタンスを生成する。

    Args:
        config: アプリケーション設定。省略時はデフォルト設定を使用する。
        pty_factory: PTY バックエンドを生成するファクトリ関数。

    Returns:
        FastAPI: ルーティング設定済みの FastAPI インスタンス。
    """
    app_config = config if config is not None else AppConfig()
    html_content = load_index_html(app_config.theme)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """サーバの起動・終了時のライフサイクル処理を行う。"""
        url = f"http://{app_config.host}:{app_config.port}"
        cmd_str = " ".join(app_config.command)
        print(f"Server started at: {url} (Command: {cmd_str})")
        if app_config.open_browser:
            webbrowser.open(url)
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def index() -> HTMLResponse:
        """ターミナル画面の HTML を返すエンドポイント。"""
        return HTMLResponse(html_content)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """ブラウザと PTY の間で双方向通信を行う WebSocket エンドポイント。"""
        await websocket.accept()
        backend = pty_factory(app_config.command)

        async def pty_to_ws() -> None:
            """PTY の出力を読み取って WebSocket クライアントへ送信する。"""
            try:
                while True:
                    output = await backend.read()
                    if not output:
                        break
                    await websocket.send_text(output)
            except Exception:
                pass
            finally:
                with contextlib.suppress(Exception):
                    await websocket.close()

        read_task = asyncio.create_task(pty_to_ws())

        try:
            while True:
                raw_msg = await websocket.receive_text()
                msg = json.loads(raw_msg)
                msg_type = msg.get("type")
                if msg_type == "input":
                    backend.write(str(msg.get("data", "")))
                elif msg_type == "resize":
                    rows = int(msg.get("rows", DEFAULT_ROWS))
                    cols = int(msg.get("cols", DEFAULT_COLS))
                    backend.resize(rows, cols)
        except WebSocketDisconnect:
            pass
        finally:
            read_task.cancel()
            backend.close()

    return app
