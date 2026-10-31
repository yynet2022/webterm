"""webterm.main モジュールのユニットテスト。"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

import webterm.main
from webterm.config import DEFAULT_HOST, DEFAULT_PORT
from webterm.main import main, parse_args, split_command


def test_split_command_windows_unquoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows 環境で引用符なしのコマンド文字列が分割されることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "win32")
    result = split_command("python -i -u")
    assert result == ["python", "-i", "-u"]


def test_split_command_windows_quoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows 環境で引用符付きパスの外側の引用符が除去されることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "win32")
    cmd = '"C:\\Program Files\\Python\\python.exe" -i'
    result = split_command(cmd)
    assert result == ["C:\\Program Files\\Python\\python.exe", "-i"]


def test_split_command_unix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unix 系環境で POSIX モードとしてコマンドが分割されることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "linux")
    result = split_command('/bin/bash -c "echo hello"')
    assert result == ["/bin/bash", "-c", "echo hello"]


def test_split_command_empty_raises() -> None:
    """空または空白のみのコマンド文字列で ValueError となることを検証する。"""
    with pytest.raises(ValueError, match="Command string must not be empty"):
        split_command("   ")


def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """引数省略時にデフォルト設定の AppConfig が返ることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "win32")
    config = parse_args([])
    assert config.command == ["cmd.exe"]
    assert config.host == DEFAULT_HOST
    assert config.port == DEFAULT_PORT
    assert config.open_browser is False


def test_parse_args_custom_options() -> None:
    """カスタム CLI 引数が AppConfig に正しく反映されることを検証する。"""
    config = parse_args(
        ["-c", "python -i", "--host", "0.0.0.0", "-p", "9000", "--open"]
    )
    assert config.command == ["python", "-i"]
    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.open_browser is True


def test_main_starts_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """エントリポイント関数 main が uvicorn.run を呼び出すことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    called_args: dict[str, Any] = {}

    def fake_uvicorn_run(app: Any, **kwargs: Any) -> None:
        called_args["app"] = app
        called_args.update(kwargs)

    monkeypatch.setattr(
        sys,
        "argv",
        ["webterm", "-c", "python -i", "--host", "127.0.0.1", "-p", "8123"],
    )
    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    main()

    assert isinstance(called_args["app"], FastAPI)
    assert called_args["host"] == "127.0.0.1"
    assert called_args["port"] == 8123
    assert called_args["log_level"] == "warning"


def test_main_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """スクリプト直接実行時 (__main__) に main が呼ばれることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    called: list[bool] = []

    def fake_uvicorn_run(app: Any, **_kwargs: Any) -> None:
        assert isinstance(app, FastAPI)
        called.append(True)

    monkeypatch.setattr(sys, "argv", ["webterm"])
    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    main_path = Path(webterm.main.__file__).resolve()
    runpy.run_path(str(main_path), run_name="__main__")

    assert called == [True]
