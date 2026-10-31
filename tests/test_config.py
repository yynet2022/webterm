"""webterm.config モジュールのユニットテスト。"""

from __future__ import annotations

import sys

import pytest

from webterm.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_THEME,
    DEFAULT_UNIX_SHELL,
    DEFAULT_WINDOWS_SHELL,
    AppConfig,
    get_default_command,
    get_default_shell,
)


def test_get_default_shell_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 環境でデフォルトシェルとして cmd.exe が返ることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "win32")
    assert get_default_shell() == DEFAULT_WINDOWS_SHELL


def test_get_default_shell_unix_with_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unix 系環境で環境変数 SHELL の値が返ることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert get_default_shell() == "/bin/zsh"


def test_get_default_shell_unix_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unix 系環境で SHELL 未設定時に bash が返ることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("SHELL", raising=False)
    assert get_default_shell() == DEFAULT_UNIX_SHELL


def test_get_default_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_default_command がデフォルトシェルのリストを返すことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "win32")
    assert get_default_command() == [DEFAULT_WINDOWS_SHELL]


def test_app_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """AppConfig のデフォルト属性値が正しく初期化されることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "win32")
    config = AppConfig()
    assert config.command == [DEFAULT_WINDOWS_SHELL]
    assert config.host == DEFAULT_HOST
    assert config.port == DEFAULT_PORT
    assert config.open_browser is False
    assert config.auto_port is True
    assert config.theme == DEFAULT_THEME
