"""OS ごとの疑似端末 (PTY) バックエンドを提供するモジュール。"""

from __future__ import annotations

import asyncio
import contextlib
import os
import struct
import subprocess
import sys
from typing import Any, Protocol

if sys.platform != "win32":
    import fcntl
    import pty
    import termios

    PtyProcess: Any = None
else:
    fcntl: Any = None
    pty: Any = None
    termios: Any = None
    from winpty import PtyProcess

READ_BUFFER_SIZE: int = 4096
TERMINATE_TIMEOUT_SECONDS: float = 1.0


class PtyBackend(Protocol):
    """PTY バックエンドの抽象化インターフェース。"""

    async def read(self) -> str:
        """PTY から出力データを非同期に読み取る。

        Returns:
            str: 読み取った文字列データ。EOF の場合は空文字列。
        """
        ...

    def write(self, data: str) -> None:
        """PTY に入力データを書き込む。

        Args:
            data: 書き込む文字列データ。
        """
        ...

    def resize(self, rows: int, cols: int) -> None:
        """PTY のウィンドウサイズを変更する。

        Args:
            rows: 新しい行数。
            cols: 新しい列数。
        """
        ...

    def close(self) -> None:
        """PTY および子プロセスを終了してリソースを解放する。"""
        ...


class UnixPtyBackend:
    """Linux / macOS (WSL含む) 用の標準 pty バックエンド。"""

    def __init__(self, command: list[str]) -> None:
        """Unix PTY バックエンドを初期化する。

        Args:
            command: 起動するコマンドと引数のリスト。
        """
        self.master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("LANG", "C.UTF-8")

        self.proc = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            env=env,
        )
        # 親プロセス側では slave_fd を即座に閉じる
        # （重要：閉じないとプロセス終了時に EOF が検知できない）
        os.close(slave_fd)

    async def read(self) -> str:
        """PTY から出力データを非同期に読み取る。

        Returns:
            str: 読み取った文字列データ。EOF の場合は空文字列。
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()

        def _on_readable() -> None:
            loop.remove_reader(self.master_fd)
            try:
                data = os.read(self.master_fd, READ_BUFFER_SIZE)
                future.set_result(data)
            except OSError:
                # Linux の pty では子プロセス終了時に EIO
                # (Input/output error) が送出される
                future.set_result(b"")

        loop.add_reader(self.master_fd, _on_readable)
        try:
            raw = await future
            return raw.decode("utf-8", errors="replace")
        finally:
            with contextlib.suppress(Exception):
                loop.remove_reader(self.master_fd)

    def write(self, data: str) -> None:
        """PTY に入力データを書き込む。

        Args:
            data: 書き込む文字列データ。
        """
        os.write(self.master_fd, data.encode("utf-8"))

    def resize(self, rows: int, cols: int) -> None:
        """PTY のウィンドウサイズを変更する。

        Args:
            rows: 新しい行数。
            cols: 新しい列数。
        """
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    def close(self) -> None:
        """PTY および子プロセスを終了してリソースを解放する。"""
        with contextlib.suppress(OSError):
            os.close(self.master_fd)
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=TERMINATE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class WindowsPtyBackend:
    """Windows 用の pywinpty (ConPTY) バックエンド。"""

    def __init__(self, command: list[str]) -> None:
        """Windows PTY バックエンドを初期化する。

        Args:
            command: 起動するコマンドと引数のリスト。
        """
        cmd_line = subprocess.list2cmdline(command)
        self.proc = PtyProcess.spawn(cmd_line)

    async def read(self) -> str:
        """PTY から出力データを非同期に読み取る。

        Returns:
            str: 読み取った文字列データ。EOF の場合は空文字列。
        """
        try:
            data = await asyncio.to_thread(
                self.proc.read,
                READ_BUFFER_SIZE,
            )
            return str(data)
        except EOFError:
            return ""

    def write(self, data: str) -> None:
        """PTY に入力データを書き込む。

        Args:
            data: 書き込む文字列データ。
        """
        self.proc.write(data)

    def resize(self, rows: int, cols: int) -> None:
        """PTY のウィンドウサイズを変更する。

        Args:
            rows: 新しい行数。
            cols: 新しい列数。
        """
        self.proc.setwinsize(rows, cols)

    def close(self) -> None:
        """PTY および子プロセスを終了してリソースを解放する。"""
        if self.proc.isalive():
            self.proc.terminate()


def create_pty(command: list[str]) -> PtyBackend:
    """実行環境に応じた PTY バックエンドを生成する。

    Args:
        command: 起動するコマンドと引数のリスト。

    Returns:
        PtyBackend: 生成された PTY バックエンドインスタンス。
    """
    if sys.platform != "win32":
        return UnixPtyBackend(command)
    return WindowsPtyBackend(command)
