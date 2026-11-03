"""webterm パッケージルート (__init__) のユニットテスト。"""

from __future__ import annotations

import webterm


def test_package_version() -> None:
    """パッケージのバージョンが 0.2.0 であることを検証する。"""
    assert webterm.__version__ == "0.2.0"
    assert webterm.__all__ == ["__version__"]
