"""アプリケーション設定を管理するモジュール。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8000
DEFAULT_UNIX_SHELL: str = "bash"
DEFAULT_WINDOWS_SHELL: str = "cmd.exe"
DEFAULT_THEME: str = "dark"
AVAILABLE_THEMES: tuple[str, ...] = (
    "dark",
    "light",
    "dracula",
    "solarized-dark",
    "monokai",
)


def get_default_shell() -> str:
    """実行環境に応じたデフォルトのシェルコマンド文字列を返す。

    Returns:
        str: デフォルトのシェルコマンド文字列。
    """
    if sys.platform != "win32":
        return os.environ.get("SHELL", DEFAULT_UNIX_SHELL)
    return DEFAULT_WINDOWS_SHELL


def get_default_command() -> list[str]:
    """実行環境に応じたデフォルトの起動コマンドリストを返す。

    Returns:
        list[str]: デフォルトの起動コマンドリスト。
    """
    return [get_default_shell()]


@dataclass
class AppConfig:
    """Web ターミナルサーバの起動設定を保持するデータクラス。

    Attributes:
        command: 起動するシェルまたは CLI コマンドの引数リスト。
        host: バインドするホスト名または IP アドレス。
        port: バインドするポート番号。
        open_browser: サーバ起動時に自動でブラウザを開くかどうか。
        auto_port: ポートが使用中の場合に自動で空きポートを探すかどうか。
        theme: ターミナルのカラーテーマ名。
    """

    command: list[str] = field(default_factory=get_default_command)
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    open_browser: bool = False
    auto_port: bool = True
    theme: str = DEFAULT_THEME
