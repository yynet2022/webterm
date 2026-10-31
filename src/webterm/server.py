"""FastAPI アプリおよび WebSocket ルーティングを提供するモジュール。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import socket
import webbrowser
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse

from webterm.config import DEFAULT_HOST, WILDCARD_HOSTS, AppConfig
from webterm.pty_backend import PtyBackend, create_pty

STATIC_DIR: Path = Path(__file__).resolve().parent / "static"
INDEX_HTML_PATH: Path = STATIC_DIR / "index.html"
THEME_PLACEHOLDER: str = "__THEME__"
DEFAULT_ROWS: int = 24
DEFAULT_COLS: int = 80
ROUTING_PROBE_TARGET: tuple[str, int] = ("8.8.8.8", 80)


def get_local_ip_addresses() -> list[str]:
    """ホストマシンに割り当てられている非ループバック IPv4 アドレス一覧を返す。

    Returns:
        list[str]: 重複を除いた検出済み IPv4 アドレスのリスト。
    """
    addresses: list[str] = []

    with (
        contextlib.suppress(OSError),
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
    ):
        sock.connect(ROUTING_PROBE_TARGET)
        primary_ip = str(sock.getsockname()[0])
        if not primary_ip.startswith("127."):
            addresses.append(primary_ip)

    with contextlib.suppress(OSError):
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = str(info[4][0])
            if not ip.startswith("127.") and ip not in addresses:
                addresses.append(ip)

    return addresses


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
    on_exit: Callable[[], None] | None = None,
) -> FastAPI:
    """設定に基づいて FastAPI アプリケーションインスタンスを生成する。

    Args:
        config: アプリケーション設定。省略時はデフォルト設定を使用する。
        pty_factory: PTY バックエンドを生成するファクトリ関数。
        on_exit: once モード時にセッション終了後呼び出されるコールバック。

    Returns:
        FastAPI: ルーティング設定済みの FastAPI インスタンス。
    """
    app_config = config if config is not None else AppConfig()
    html_content = load_index_html(app_config.theme)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """サーバの起動・終了時のライフサイクル処理を行う。"""
        cmd_str = " ".join(app_config.command)
        is_wildcard = app_config.host in WILDCARD_HOSTS
        primary_host = DEFAULT_HOST if is_wildcard else app_config.host
        primary_url = (
            f"http://{primary_host}:{app_config.port}/{app_config.token}"
        )
        print(f"Server started at: {primary_url} (Command: {cmd_str})")

        if is_wildcard:
            for ip in get_local_ip_addresses():
                lan_url = f"http://{ip}:{app_config.port}/{app_config.token}"
                print(f"and {lan_url}")

        print("Press Ctrl+C to stop the server.")

        if app_config.open_browser:
            webbrowser.open(primary_url)
        yield

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/{token}")
    async def index(token: str) -> HTMLResponse:
        """トークンを検証し、ターミナル画面の HTML を返すエンドポイント。"""
        if not secrets.compare_digest(token, app_config.token):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )
        return HTMLResponse(html_content)

    @app.websocket("/{token}/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str) -> None:
        """ブラウザと PTY の間で双方向通信を行う WebSocket エンドポイント。"""
        if not secrets.compare_digest(token, app_config.token):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

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
            if app_config.once and on_exit is not None:
                on_exit()

    return app
