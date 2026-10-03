#!/usr/bin/env bash
# local-genai-mcp のセットアップと Claude Code への登録を行う
set -euo pipefail

NAME="local-genai"
SCOPE="user"
VENV_DIR="${LOCAL_GENAI_MCP_VENV:-$HOME/.local/share/local-genai-mcp/venv}"
ASSUME_YES=0
DRY_RUN=0
REGISTER=1

usage() {
  cat <<'EOF'
使い方: ./install.sh [オプション]

  --scope <user|project|local>  Claude Code への登録範囲(既定: user = すべてのフォルダで使える)
  --name <名前>                 Claude Code に登録するMCPサーバ名(既定: local-genai)
  --venv <フォルダ>             Python仮想環境の置き場所
                                (既定: ~/.local/share/local-genai-mcp/venv。
                                 このフォルダがNAS上にあっても、仮想環境はローカルに置く)
  --no-register                 依存関係の準備と接続確認だけ行い、Claude Code には登録しない
  --dry-run                     実行するコマンドを表示するだけで、実際には何もしない
  -y, --yes                     確認の質問にすべて「はい」と答える
  -h, --help                    このヘルプを表示する
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --venv) VENV_DIR="$2"; shift 2 ;;
    --no-register) REGISTER=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "不明なオプションです: $1" >&2; usage; exit 1 ;;
  esac
done

case "$SCOPE" in
  user|project|local) ;;
  *) echo "--scope には user / project / local のいずれかを指定してください" >&2; exit 1 ;;
esac

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run() {
  echo "+ $*"
  if [ "$DRY_RUN" = 0 ]; then "$@"; fi
}

confirm() {
  if [ "$ASSUME_YES" = 1 ]; then return 0; fi
  local answer
  read -r -p "$1 [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]]
}

echo "== local-genai-mcp のセットアップ"
echo "プロジェクト: $PROJECT_DIR"
echo "仮想環境:     $VENV_DIR"
echo

# 1. uv
if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  if confirm "uv が見つかりません。公式のインストールスクリプト(https://astral.sh/uv/install.sh)でインストールしますか?"; then
    run sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "uv をインストールしてから、もう一度実行してください: https://docs.astral.sh/uv/" >&2
    exit 1
  fi
fi
UV_BIN="$(command -v uv || echo "$HOME/.local/bin/uv")"
echo "uv: $UV_BIN"

# 2. Claude Code
if [ "$REGISTER" = 1 ]; then
  if ! command -v claude >/dev/null 2>&1; then
    echo "claude コマンドが見つかりません。Claude Code をインストールしてから実行してください。" >&2
    echo "(登録せずに準備だけ行う場合は --no-register を付けてください)" >&2
    exit 1
  fi
  CLAUDE_BIN="$(command -v claude)"
  echo "claude: $CLAUDE_BIN"
fi
echo

# 3. 依存関係のインストール
export UV_PROJECT_ENVIRONMENT="$VENV_DIR"
run mkdir -p "$(dirname "$VENV_DIR")"
run "$UV_BIN" sync --project "$PROJECT_DIR" --no-dev

# 4. 設定ファイル
CONFIG_CREATED=0
if [ ! -f "$PROJECT_DIR/config.toml" ]; then
  run cp "$PROJECT_DIR/config.example.toml" "$PROJECT_DIR/config.toml"
  run chmod 600 "$PROJECT_DIR/config.toml"
  CONFIG_CREATED=1
fi

# 5. 接続確認
echo
if [ "$CONFIG_CREATED" = 1 ]; then
  echo "config.toml を作成しました。Ollama と Forge Neo のアドレスなどを書き換えてから、以下で接続確認してください:"
  echo "  UV_PROJECT_ENVIRONMENT=\"$VENV_DIR\" uv run --project \"$PROJECT_DIR\" --no-dev local-genai-mcp --check"
else
  echo "== 接続確認"
  run "$UV_BIN" run --project "$PROJECT_DIR" --no-dev local-genai-mcp --check \
    || echo "(接続できないサービスがあります。config.toml や相手側の起動状態を確認してください。登録は続行します)"
fi

if [ "$REGISTER" = 0 ]; then
  echo
  echo "--no-register のため、Claude Code への登録は行いませんでした。"
  exit 0
fi

# 6. Claude Code への登録
echo
echo "== Claude Code への登録(名前: $NAME、範囲: $SCOPE)"
if [ "$SCOPE" = "project" ]; then
  echo "※ project 範囲では、今いるフォルダ($(pwd))の .mcp.json に登録されます。"
fi
if "$CLAUDE_BIN" mcp get "$NAME" >/dev/null 2>&1; then
  if confirm "「$NAME」はすでに登録されています。登録し直しますか?"; then
    run "$CLAUDE_BIN" mcp remove --scope "$SCOPE" "$NAME" || true
  else
    echo "登録はそのままにしました。"
    exit 0
  fi
fi
run "$CLAUDE_BIN" mcp add --scope "$SCOPE" "$NAME" -e "UV_PROJECT_ENVIRONMENT=$VENV_DIR" -- \
  "$UV_BIN" run --project "$PROJECT_DIR" --no-dev local-genai-mcp

echo
if [ "$DRY_RUN" = 1 ]; then
  echo "(--dry-run のため、上のコマンドは表示しただけで実行していません)"
  exit 0
fi
echo "完了しました。Claude Code を起動し直し、会話中に /mcp と入力すると接続状態を確認できます。"
echo "設定ファイル: $PROJECT_DIR/config.toml(書き換えたら Claude Code を起動し直してください)"
