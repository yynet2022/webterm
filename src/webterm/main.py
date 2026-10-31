"""CLI 引数の解析と Web ターミナルサーバの起動を行うエントリポイント。"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Sequence

import uvicorn

from webterm.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    AppConfig,
    get_default_shell,
)
from webterm.server import create_app


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
        default=DEFAULT_PORT,
        help="Port number to bind to (default: 8000)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the browser when the server starts",
    )
    args = parser.parse_args(argv)

    return AppConfig(
        command=split_command(args.command),
        host=args.host,
        port=args.port,
        open_browser=args.open,
    )


def main() -> None:
    """CLI のメインエントリポイント。"""
    config = parse_args()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")


if __name__ == "__main__":
    main()
