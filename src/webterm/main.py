"""CLI 引数の解析と Web ターミナルサーバの起動を行うエントリポイント。"""

from __future__ import annotations

import argparse
import contextlib
import shlex
import socket
import sys
from collections.abc import Sequence

import uvicorn

from webterm.config import (
    AVAILABLE_THEMES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_THEME,
    WILDCARD_HOST,
    WILDCARD_HOSTS,
    AppConfig,
    get_default_shell,
)
from webterm.server import create_app

MIN_PORT: int = 1
MAX_PORT: int = 65535


def is_port_available(host: str, port: int) -> bool:
    """指定されたホストとポート番号がバインド可能か判定する。

    Args:
        host: バインド先ホスト名または IP アドレス。
        port: 確認するポート番号。

    Returns:
        bool: 利用可能なら True、使用中またはバインド不可なら False。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True


def resolve_port(host: str, port: int, *, auto_increment: bool) -> int:
    """利用可能なポート番号を決定する。

    Args:
        host: バインド先ホスト名または IP アドレス。
        port: 開始または指定されたポート番号。
        auto_increment: 使用中の場合にインクリメントして探索するかどうか。

    Returns:
        int: バインド可能なポート番号。

    Raises:
        ValueError: ポート番号が有効範囲外の場合。
        RuntimeError: 利用可能なポートが見つからない場合。
    """
    if not (MIN_PORT <= port <= MAX_PORT):
        raise ValueError(
            f"Port number must be between {MIN_PORT} and {MAX_PORT}: {port}"
        )

    if not auto_increment:
        if not is_port_available(host, port):
            raise RuntimeError(f"Port {port} is already in use on {host}.")
        return port

    for candidate in range(port, MAX_PORT + 1):
        if is_port_available(host, candidate):
            return candidate

    raise RuntimeError(
        f"No available port found on {host} in range {port}-{MAX_PORT}."
    )


def split_command(command_str: str) -> list[str]:
    """コマンド文字列をプラットフォームに応じて引数リストに分割する。

    Windows 環境ではバックスラッシュを含むパスが破損しないよう
    posix=False で分割し、外側の引用符を除去する。

    Args:
        command_str: 分割対象のコマンド文字列。

    Returns:
        list[str]: 分割されたコマンドと引数のリスト。

    Raises:
        ValueError: コマンド文字列が空または空白のみの場合。
    """
    if sys.platform == "win32":
        raw_parts = shlex.split(command_str, posix=False)
        parts = [
            part[1:-1]
            if len(part) >= 2 and part.startswith('"') and part.endswith('"')
            else part
            for part in raw_parts
        ]
    else:
        parts = shlex.split(command_str, posix=True)

    if not parts:
        raise ValueError("Command string must not be empty.")
    return parts


def parse_args(argv: Sequence[str] | None = None) -> AppConfig:
    """コマンドライン引数を解析して AppConfig を生成する。

    Args:
        argv: 解析する引数シーケンス。None の場合は sys.argv[1:] を使用。

    Returns:
        AppConfig: 解析結果から生成された設定オブジェクト。
    """
    parser = argparse.ArgumentParser(
        description="Browser-based terminal emulator launcher"
    )
    parser.add_argument(
        "-c",
        "--command",
        default=get_default_shell(),
        help=(
            "Shell or CLI command to launch "
            "(e.g. 'bash', 'python -i', 'cmd.exe')"
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Host address to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,
        help="Port number to bind to (default: 8000, auto-increment if busy)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the browser when the server starts",
    )
    parser.add_argument(
        "-t",
        "--theme",
        choices=AVAILABLE_THEMES,
        default=DEFAULT_THEME,
        help="Color theme for the terminal (default: dark)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Stop the server after the first terminal session ends",
    )
    args = parser.parse_args(argv)

    host = WILDCARD_HOST if args.host in WILDCARD_HOSTS else args.host
    port = DEFAULT_PORT if args.port is None else args.port
    auto_port = args.port is None

    return AppConfig(
        command=split_command(args.command),
        host=host,
        port=port,
        open_browser=args.open,
        auto_port=auto_port,
        theme=args.theme,
        once=args.once,
    )


def main() -> None:
    """CLI のメインエントリポイント。"""
    config = parse_args()
    try:
        config.port = resolve_port(
            config.host,
            config.port,
            auto_increment=config.auto_port,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    server_ref: list[uvicorn.Server] = []

    def stop_server() -> None:
        """実行中の Uvicorn サーバに終了フラグを設定する。"""
        for srv in server_ref:
            srv.should_exit = True

    app = create_app(config, on_exit=stop_server)
    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level="warning",
    )
    server = uvicorn.Server(uvicorn_config)
    server_ref.append(server)
    with contextlib.suppress(KeyboardInterrupt):
        server.run()


if __name__ == "__main__":
    main()
