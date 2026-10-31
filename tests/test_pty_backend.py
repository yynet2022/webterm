"""webterm.pty_backend モジュールのユニットテスト。"""

from __future__ import annotations

import asyncio
import os
import runpy
import struct
import subprocess
import sys
import types
from pathlib import Path

import pytest

import webterm.pty_backend as pty_backend
from webterm.pty_backend import (
    READ_BUFFER_SIZE,
    TERMINATE_TIMEOUT_SECONDS,
    UnixPtyBackend,
    WindowsPtyBackend,
    create_pty,
)


class DummyUnixProc:
    """UnixPtyBackend テスト用のダミー Popen オブジェクト。"""

    def __init__(
        self,
        *,
        poll_result: int | None = None,
        timeout_on_wait: bool = False,
    ) -> None:
        """ダミープロセスを初期化する。

        Args:
            poll_result: poll() が返す終了コード。稼働中は None。
            timeout_on_wait: wait() 時に TimeoutExpired を送出するか。
        """
        self.poll_result = poll_result
        self.timeout_on_wait = timeout_on_wait
        self.terminated: bool = False
        self.waited_timeout: float | None = None
        self.killed: bool = False

    def poll(self) -> int | None:
        """プロセスの終了状態を返す。

        Returns:
            int | None: 終了コードまたは None。
        """
        return self.poll_result

    def terminate(self) -> None:
        """プロセス終了要求を記録する。"""
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        """プロセスの終了待機をシミュレートする。

        Args:
            timeout: タイムアウト秒数。

        Returns:
            int: 終了コード 0。

        Raises:
            subprocess.TimeoutExpired: timeout_on_wait が True の場合。
        """
        self.waited_timeout = timeout
        if self.timeout_on_wait:
            raise subprocess.TimeoutExpired(cmd="dummy", timeout=timeout or 0)
        return 0

    def kill(self) -> None:
        """プロセスの強制終了要求を記録する。"""
        self.killed = True


class DummyWinPtyProc:
    """WindowsPtyBackend テスト用のダミー PtyProcess オブジェクト。"""

    def __init__(
        self,
        *,
        alive: bool = True,
        raise_eof: bool = False,
    ) -> None:
        """ダミー Windows PTY プロセスを初期化する。

        Args:
            alive: isalive() が返す真偽値。
            raise_eof: read() 時に EOFError を送出するかどうか。
        """
        self.alive = alive
        self.raise_eof = raise_eof
        self.written: list[str] = []
        self.winsizes: list[tuple[int, int]] = []
        self.terminated: bool = False
        self.last_read_size: int | None = None

    def read(self, size: int) -> str:
        """データの読み取りをシミュレートする。

        Args:
            size: 読み取りバッファサイズ。

        Returns:
            str: ダミー出力文字列。

        Raises:
            EOFError: raise_eof が True の場合。
        """
        self.last_read_size = size
        if self.raise_eof:
            raise EOFError
        return "windows output"

    def write(self, data: str) -> None:
        """書き込みデータを記録する。

        Args:
            data: 書き込まれた文字列。
        """
        self.written.append(data)

    def setwinsize(self, rows: int, cols: int) -> None:
        """ウィンドウサイズ変更を記録する。

        Args:
            rows: 行数。
            cols: 列数。
        """
        self.winsizes.append((rows, cols))

    def isalive(self) -> bool:
        """プロセスが生存しているかを返す。

        Returns:
            bool: 生存状態。
        """
        return self.alive

    def terminate(self) -> None:
        """プロセス終了要求を記録する。"""
        self.terminated = True


def _setup_unix_mocks(
    monkeypatch: pytest.MonkeyPatch,
    dummy_proc: DummyUnixProc | None = None,
) -> tuple[UnixPtyBackend, DummyUnixProc, list[int]]:
    """UnixPtyBackend の初期化に必要なモックを設定してインスタンスを返す。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
        dummy_proc: 使用する DummyUnixProc。省略時は新規作成。

    Returns:
        tuple[UnixPtyBackend, DummyUnixProc, list[int]]:
            生成されたバックエンド、ダミープロセス、close された fd リスト。
    """
    proc = dummy_proc if dummy_proc is not None else DummyUnixProc()
    closed_fds: list[int] = []

    fake_pty = types.SimpleNamespace(openpty=lambda: (10, 11))
    monkeypatch.setattr(pty_backend, "pty", fake_pty)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: proc,
    )
    monkeypatch.setattr(os, "close", lambda fd: closed_fds.append(fd))

    backend = UnixPtyBackend(["/bin/bash"])
    return backend, proc, closed_fds


def test_unix_platform_module_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 Windows 環境としてモジュールを読み込んだ際の分岐を検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "fcntl", types.ModuleType("fcntl"))
    monkeypatch.setitem(sys.modules, "pty", types.ModuleType("pty"))
    monkeypatch.setitem(sys.modules, "termios", types.ModuleType("termios"))

    module_path = Path(pty_backend.__file__).resolve()
    namespace = runpy.run_path(str(module_path))
    assert namespace["PtyProcess"] is None


async def test_unix_pty_backend_read_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UnixPtyBackend.read がデータ読み取りに成功することを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    backend, _, closed_fds = _setup_unix_mocks(monkeypatch)
    assert backend.master_fd == 10
    assert closed_fds == [11]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "add_reader",
        lambda _fd, callback: callback(),
    )
    monkeypatch.setattr(loop, "remove_reader", lambda _fd: None)
    monkeypatch.setattr(
        os,
        "read",
        lambda fd, size: b"hello unix" if (fd, size) == (10, 4096) else b"",
    )

    result = await backend.read()
    assert result == "hello unix"


async def test_unix_pty_backend_read_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UnixPtyBackend.read が OSError 発生時に空文字を返すことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    backend, _, _ = _setup_unix_mocks(monkeypatch)

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "add_reader",
        lambda _fd, callback: callback(),
    )
    monkeypatch.setattr(loop, "remove_reader", lambda _fd: None)

    def raise_eio(_fd: int, _size: int) -> bytes:
        raise OSError("Input/output error")

    monkeypatch.setattr(os, "read", raise_eio)

    result = await backend.read()
    assert result == ""


def test_unix_pty_backend_write_and_resize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UnixPtyBackend の write と resize の動作を検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    backend, _, _ = _setup_unix_mocks(monkeypatch)

    written: list[tuple[int, bytes]] = []

    def fake_write(fd: int, data: bytes) -> int:
        written.append((fd, data))
        return len(data)

    monkeypatch.setattr(os, "write", fake_write)

    ioctl_calls: list[tuple[int, int, bytes]] = []

    def fake_ioctl(fd: int, op: int, arg: bytes) -> int:
        ioctl_calls.append((fd, op, arg))
        return 0

    fake_fcntl = types.SimpleNamespace(ioctl=fake_ioctl)
    fake_termios = types.SimpleNamespace(TIOCSWINSZ=0x5414)
    monkeypatch.setattr(pty_backend, "fcntl", fake_fcntl)
    monkeypatch.setattr(pty_backend, "termios", fake_termios)

    backend.write("pwd\n")
    backend.resize(25, 90)

    assert written == [(10, b"pwd\n")]
    expected_winsize = struct.pack("HHHH", 25, 90, 0, 0)
    assert ioctl_calls == [(10, 0x5414, expected_winsize)]


def test_unix_pty_backend_close_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UnixPtyBackend.close の各終了パターンを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    # 1. プロセスが既に終了している場合 (poll() != None)
    exited_proc = DummyUnixProc(poll_result=0)
    backend1, _, closed_fds1 = _setup_unix_mocks(monkeypatch, exited_proc)
    backend1.close()
    assert 10 in closed_fds1
    assert exited_proc.terminated is False

    # 2. プロセスが稼働中で wait() が正常完了する場合
    running_proc = DummyUnixProc(poll_result=None, timeout_on_wait=False)
    backend2, _, _ = _setup_unix_mocks(monkeypatch, running_proc)
    backend2.close()
    assert running_proc.terminated is True
    assert running_proc.waited_timeout == TERMINATE_TIMEOUT_SECONDS
    assert running_proc.killed is False

    # 3. プロセスが稼働中で wait() がタイムアウトする場合
    stubborn_proc = DummyUnixProc(poll_result=None, timeout_on_wait=True)
    backend3, _, _ = _setup_unix_mocks(monkeypatch, stubborn_proc)
    backend3.close()
    assert stubborn_proc.terminated is True
    assert stubborn_proc.killed is True


async def test_windows_pty_backend_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WindowsPtyBackend の読み書き・リサイズ・クローズを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    dummy_proc = DummyWinPtyProc(alive=True, raise_eof=False)
    spawned_cmds: list[str] = []

    def fake_spawn(cmd_line: str) -> DummyWinPtyProc:
        spawned_cmds.append(cmd_line)
        return dummy_proc

    fake_pty_process = types.SimpleNamespace(spawn=fake_spawn)
    monkeypatch.setattr(pty_backend, "PtyProcess", fake_pty_process)

    backend = WindowsPtyBackend(["cmd.exe", "/c", "echo hello"])
    assert spawned_cmds == ['cmd.exe /c "echo hello"']

    output = await backend.read()
    assert output == "windows output"
    assert dummy_proc.last_read_size == READ_BUFFER_SIZE

    backend.write("dir\r\n")
    assert dummy_proc.written == ["dir\r\n"]

    backend.resize(40, 120)
    assert dummy_proc.winsizes == [(40, 120)]

    backend.close()
    assert dummy_proc.terminated is True


async def test_windows_pty_backend_eof_and_dead_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WindowsPtyBackend の EOF 読み取りと停止済みクローズを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    dummy_proc = DummyWinPtyProc(alive=False, raise_eof=True)
    fake_pty_process = types.SimpleNamespace(spawn=lambda _cmd: dummy_proc)
    monkeypatch.setattr(pty_backend, "PtyProcess", fake_pty_process)

    backend = WindowsPtyBackend(["cmd.exe"])
    output = await backend.read()
    assert output == ""

    backend.close()
    assert dummy_proc.terminated is False


def test_create_pty_dispatches_by_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ファクトリ関数 create_pty が環境別のバックエンドを返すことを検証する。

    Args:
        monkeypatch: pytest の MonkeyPatch フィクスチャ。
    """
    dummy_win = DummyWinPtyProc()

    def fake_pty_process(_cmd: str) -> DummyWinPtyProc:
        return dummy_win

    monkeypatch.setattr(
        pty_backend,
        "PtyProcess",
        types.SimpleNamespace(spawn=fake_pty_process),
    )

    monkeypatch.setattr(sys, "platform", "win32")
    win_backend = create_pty(["cmd.exe"])
    assert isinstance(win_backend, WindowsPtyBackend)

    _setup_unix_mocks(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    unix_backend = create_pty(["/bin/bash"])
    assert isinstance(unix_backend, UnixPtyBackend)
