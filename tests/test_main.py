"""webterm.main モジュールのユニットテスト。"""

from __future__ import annotations

import runpy
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

import webterm.main
from webterm.config import DEFAULT_HOST, DEFAULT_PORT
from webterm.main import (
    MAX_PORT,
    is_port_available,
    main,
    parse_args,
    resolve_port,
    split_command,
)


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
    assert config.auto_port is True


def test_parse_args_custom_options() -> None:
    """カスタム CLI 引数が AppConfig に正しく反映されることを検証する。"""
    config = parse_args(
        ["-c", "python -i", "--host", "0.0.0.0", "-p", "9000", "--open"]
    )
    assert config.command == ["python", "-i"]
    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.open_browser is True
    assert config.auto_port is False


def test_is_port_available_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """ソケットのバインドに成功した場合に True が返ることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """

    class DummySocket:
        def __enter__(self) -> DummySocket:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def bind(self, address: tuple[str, int]) -> None:
            pass

    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: DummySocket()
    )
    assert is_port_available("127.0.0.1", 8000) is True


def test_is_port_available_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """ソケットのバインド時に OSError が起きたら False が返ることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """

    class BusySocket:
        def __enter__(self) -> BusySocket:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def bind(self, address: tuple[str, int]) -> None:
            raise OSError("Address already in use")

    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: BusySocket())
    assert is_port_available("127.0.0.1", 8000) is False


def test_resolve_port_invalid_range() -> None:
    """有効範囲外のポート番号で ValueError が発生することを検証する。"""
    with pytest.raises(ValueError, match="Port number must be between"):
        resolve_port("127.0.0.1", 0, auto_increment=False)
    with pytest.raises(ValueError, match="Port number must be between"):
        resolve_port("127.0.0.1", 65536, auto_increment=True)


def test_resolve_port_explicit_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """明示指定されたポートが空いている場合にそのまま返ることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: True
    )
    assert resolve_port("127.0.0.1", 8080, auto_increment=False) == 8080


def test_resolve_port_explicit_busy_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """明示指定されたポートが使用中の場合に RuntimeError となることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: False
    )
    with pytest.raises(RuntimeError, match="Port 8080 is already in use"):
        resolve_port("127.0.0.1", 8080, auto_increment=False)


def test_resolve_port_auto_increment_finds_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自動探索時に使用中ポートをスキップして空きポートを返すことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(
        webterm.main,
        "is_port_available",
        lambda host, port: port >= 8002,
    )
    assert resolve_port("127.0.0.1", 8000, auto_increment=True) == 8002


def test_resolve_port_auto_increment_exhausted_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自動探索で空きポートがない場合に RuntimeError となることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: False
    )
    with pytest.raises(RuntimeError, match="No available port found"):
        resolve_port("127.0.0.1", MAX_PORT - 1, auto_increment=True)


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
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: True
    )
    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    main()

    assert isinstance(called_args["app"], FastAPI)
    assert called_args["host"] == "127.0.0.1"
    assert called_args["port"] == 8123
    assert called_args["log_level"] == "warning"


def test_main_exits_on_busy_explicit_port(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """明示指定したポートが使用中の場合にエラー出力して終了することを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
        capsys: pytest の標準出力・標準エラー出力キャプチャフィクスチャ。
    """
    monkeypatch.setattr(sys, "argv", ["webterm", "-p", "8080"])
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: False
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Port 8080 is already in use" in captured.err


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
    monkeypatch.setattr(
        socket.socket,
        "bind",
        lambda self, address: None,
    )
    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    main_path = Path(webterm.main.__file__).resolve()
    runpy.run_path(str(main_path), run_name="__main__")

    assert called == [True]
