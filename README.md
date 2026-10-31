# webterm

FastAPI と xterm.js を使用した、ブラウザベースのターミナルエミュレータ起動ツールです。

## 特徴

- **ブラウザ上で動作するフル機能のターミナル**: フロントエンドに `xterm.js`（`FitAddon` および `Unicode11Addon` 込み）を採用し、ウィンドウのリサイズや日本語（CJK文字）の表示に対応しています。
- **クロスプラットフォーム対応**:
  - Linux / macOS / WSL 環境では標準ライブラリの `pty` を使用します。
  - Windows 環境では `pywinpty`（ConPTY）を使用します。
- **任意のシェル・CLI コマンドを起動可能**: デフォルトのシェルだけでなく、任意の対話型 CLI ツールやスクリプトを指定してブラウザ経由で操作できます。

## ディレクトリ構成

```text
./
├── .gitignore
├── pyproject.toml
├── README.md
├── src/
│   └── webterm/
│       ├── __init__.py
│       ├── config.py       # アプリケーション設定管理 (AppConfig)
│       ├── main.py         # CLI 引数解析と起動エントリポイント
│       ├── pty_backend.py  # OS 別 PTY バックエンド実装
│       ├── server.py       # FastAPI アプリケーションと WebSocket 処理
│       └── static/
│           └── index.html  # フロントエンド (HTML / CSS / JS)
└── tests/
    ├── __init__.py
    ├── test_config.py       # config モジュールのユニットテスト
    ├── test_main.py         # main モジュールのユニットテスト
    ├── test_pty_backend.py  # pty_backend モジュールのユニットテスト
    └── test_server.py       # server モジュールのユニットテスト
```

## 動作要件

- Python 3.10 以上

## インストール

リポジトリのルートディレクトリで以下を実行してインストールします。

```bash
pip install -e .
```

開発用ツール（`pytest`, `ruff`, `mypy`, `httpx2`）も含めてインストールする場合は以下を実行します。

```bash
pip install -e ".[dev]"
```

## 使い方

インストール後、`webterm` コマンドが使用可能になります。

```bash
# デフォルトのシェル（Windows では cmd.exe、Unix 系では $SHELL または bash）で起動
webterm

# 起動と同時に自動でデフォルトブラウザを開く
webterm --open

# 起動するコマンドやポート番号を指定する例
webterm -c "python -i" -p 8080 --open
```

### コマンドラインオプション

| オプション | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `-c`, `--command` | Unix: `$SHELL` (`bash`) / Windows: `cmd.exe` | 起動するシェルまたは CLI コマンド |
| `--host` | `127.0.0.1` | バインドするホスト名 |
| `-p`, `--port` | `8000` | バインドするポート番号（未指定時は `8000` から空きポートを自動探索、指定時は使用不可ならエラー終了） |
| `--open` | `False` | 起動時に自動でブラウザを開く |

## 開発・テスト

コード品質チェックおよびユニットテストは以下のコマンドで実行できます。

```bash
# Linter とフォーマッタのチェック
ruff check src tests
ruff format --check src tests

# 型チェック
mypy src tests

# ユニットテストの実行
pytest
```

---

## ライセンス

MIT License
