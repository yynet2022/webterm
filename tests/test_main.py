"""webterm.main モジュールのユニットテスト。"""

from __future__ import annotations

import asyncio
import errno
import runpy
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

import webterm.main
from webterm.config import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_THEME
from webterm.main import (
    MAX_PORT,
    is_port_available,
    main,
    parse_args,
    resolve_port,
    split_command,
)
from webterm.server import create_app


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
    with pytest.raises(ValueError, match="Command string must not be empty"):
        split_command('""')


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
    assert config.theme == DEFAULT_THEME
    assert config.once is False


def test_parse_args_custom_options() -> None:
    """カスタム CLI 引数が AppConfig に正しく反映されることを検証する。"""
    config = parse_args(
        [
            "-c",
            "python -i",
            "--host",
            "0.0.0.0",
            "-p",
            "9000",
            "--open",
            "-t",
            "dracula",
            "--once",
        ]
    )
    assert config.command == ["python", "-i"]
    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.open_browser is True
    assert config.auto_port is False
    assert config.theme == "dracula"
    assert config.once is True


def test_parse_args_wildcard_host_shorthand() -> None:
    """--host 0 が 0.0.0.0 に正規化されることを検証する。"""
    config = parse_args(["--host", "0"])
    assert config.host == "0.0.0.0"


def test_parse_args_invalid_theme_raises() -> None:
    """未定義のテーマ名を指定した場合に SystemExit となることを検証する。"""
    with pytest.raises(SystemExit):
        parse_args(["--theme", "unknown-theme"])


def test_parse_args_ssl_options_valid(tmp_path: Path) -> None:
    """有効な SSL 鍵・証明書ファイルを指定した場合の解析を検証する。

    Args:
        tmp_path: pytest の一時ディレクトリフィクスチャ。
    """
    key_file = tmp_path / "server.key"
    cert_file = tmp_path / "server.crt"
    key_file.write_text("dummy-key", encoding="utf-8")
    cert_file.write_text("dummy-cert", encoding="utf-8")

    config = parse_args(
        [
            "--ssl-keyfile",
            str(key_file),
            "--ssl-certfile",
            str(cert_file),
        ]
    )
    assert config.ssl_keyfile == str(key_file)
    assert config.ssl_certfile == str(cert_file)


def test_parse_args_ssl_options_invalid(tmp_path: Path) -> None:
    """SSL 引数の片方指定や存在しないファイルで ValueError となることを検証。

    Args:
        tmp_path: pytest の一時ディレクトリフィクスチャ。
    """
    key_file = tmp_path / "server.key"
    key_file.write_text("dummy-key", encoding="utf-8")
    missing_file = tmp_path / "missing.pem"

    with pytest.raises(
        ValueError,
        match="Both --ssl-keyfile and --ssl-certfile must be specified",
    ):
        parse_args(["--ssl-keyfile", str(key_file)])

    with pytest.raises(
        ValueError,
        match="SSL key file not found",
    ):
        parse_args(
            [
                "--ssl-keyfile",
                str(missing_file),
                "--ssl-certfile",
                str(key_file),
            ]
        )

    with pytest.raises(
        ValueError,
        match="SSL certificate file not found",
    ):
        parse_args(
            [
                "--ssl-keyfile",
                str(key_file),
                "--ssl-certfile",
                str(missing_file),
            ]
        )


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


def test_is_port_available_unresolvable_host_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ホスト名解決エラー時に ValueError が送出されることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """

    class GaiErrorSocket:
        def __enter__(self) -> GaiErrorSocket:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def bind(self, address: tuple[str, int]) -> None:
            raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: GaiErrorSocket()
    )
    with pytest.raises(ValueError, match="Cannot resolve host"):
        is_port_available("invalid.host.local", 8000)


def test_is_port_available_addr_not_avail_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """バインド不能アドレス指定時に ValueError が送出されることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """

    class AddrNotAvailSocket:
        def __enter__(self) -> AddrNotAvailSocket:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def bind(self, address: tuple[str, int]) -> None:
            raise OSError(errno.EADDRNOTAVAIL, "Cannot assign address")

    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: AddrNotAvailSocket()
    )
    with pytest.raises(ValueError, match="Cannot bind to address"):
        is_port_available("192.0.2.99", 8000)


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
    """エントリポイント関数 main が uvicorn.Server.run を呼ぶことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    created_servers: list[Any] = []
    captured_on_exit: list[Any] = []

    def spy_create_app(config: Any, **kwargs: Any) -> FastAPI:
        captured_on_exit.append(kwargs.get("on_exit"))
        return create_app(config, **kwargs)

    class FakeServer:
        def __init__(self, config: uvicorn.Config) -> None:
            self.config = config
            self.should_exit = False
            self.ran = False
            created_servers.append(self)

        def run(self) -> None:
            self.ran = True
            if captured_on_exit and captured_on_exit[0] is not None:
                captured_on_exit[0]()

    monkeypatch.setattr(
        sys,
        "argv",
        ["webterm", "-c", "python -i", "--host", "127.0.0.1", "-p", "8123"],
    )
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: True
    )
    monkeypatch.setattr(webterm.main, "create_app", spy_create_app)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    main()

    assert len(created_servers) == 1
    srv = created_servers[0]
    assert isinstance(srv.config.app, FastAPI)
    assert srv.config.host == "127.0.0.1"
    assert srv.config.port == 8123
    assert srv.config.log_level == "warning"
    assert srv.ran is True
    assert srv.should_exit is True


def test_main_stop_server_with_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ループ稼働時に call_later 経由で should_exit が立つことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    created_servers: list[Any] = []
    captured_on_exit: list[Any] = []
    scheduled_delays: list[float] = []

    def spy_create_app(config: Any, **kwargs: Any) -> FastAPI:
        captured_on_exit.append(kwargs.get("on_exit"))
        return create_app(config, **kwargs)

    class DummyLoop:
        def call_later(self, delay: float, callback: Any) -> None:
            scheduled_delays.append(delay)
            callback()

    class FakeServer:
        def __init__(self, config: uvicorn.Config) -> None:
            self.config = config
            self.should_exit = False
            created_servers.append(self)

        def run(self) -> None:
            if captured_on_exit and captured_on_exit[0] is not None:
                assert isinstance(self.config.app, FastAPI)
                self.config.app.state.active_sessions = 1
                captured_on_exit[0]()
                assert self.should_exit is False
                self.config.app.state.active_sessions = 0
                captured_on_exit[0]()

    monkeypatch.setattr(sys, "argv", ["webterm", "--once"])
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: True
    )
    monkeypatch.setattr(webterm.main, "create_app", spy_create_app)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: DummyLoop())
    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    main()

    assert len(created_servers) == 1
    assert scheduled_delays == [0.05, 0.05]
    assert created_servers[0].should_exit is True


def test_main_suppresses_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+C による KeyboardInterrupt が抑制され正常終了することを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """

    class InterruptingServer:
        def __init__(self, config: uvicorn.Config) -> None:
            self.config = config

        def run(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(sys, "argv", ["webterm"])
    monkeypatch.setattr(
        webterm.main, "is_port_available", lambda host, port: True
    )
    monkeypatch.setattr(uvicorn, "Server", InterruptingServer)

    main()


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


def test_main_exits_on_empty_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """空のコマンド文字列が指定された場合にエラー終了することを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
        capsys: pytest の標準出力・標準エラー出力キャプチャフィクスチャ。
    """
    monkeypatch.setattr(sys, "argv", ["webterm", "-c", "   "])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Command string must not be empty" in captured.err


def test_main_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """スクリプト直接実行時 (__main__) に main が呼ばれることを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    called: list[bool] = []

    class DummyServer:
        def __init__(self, config: uvicorn.Config) -> None:
            assert isinstance(config.app, FastAPI)

        def run(self) -> None:
            called.append(True)

    monkeypatch.setattr(sys, "argv", ["webterm"])
    monkeypatch.setattr(
        socket.socket,
        "bind",
        lambda self, address: None,
    )
    monkeypatch.setattr(uvicorn, "Server", DummyServer)

    main_path = Path(webterm.main.__file__).resolve()
    runpy.run_path(str(main_path), run_name="__main__")

    assert called == [True]
