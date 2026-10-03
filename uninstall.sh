#!/usr/bin/env bash
# local-genai-mcp の Claude Code への登録を解除する
set -euo pipefail

NAME="local-genai"
SCOPE="user"
VENV_DIR="${LOCAL_GENAI_MCP_VENV:-$HOME/.local/share/local-genai-mcp/venv}"
REMOVE_VENV=0

while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --venv) VENV_DIR="$2"; shift 2 ;;
    --remove-venv) REMOVE_VENV=1; shift ;;
    -h|--help)
      echo "使い方: ./uninstall.sh [--scope user|project|local] [--name 名前] [--remove-venv]"
      echo "  --remove-venv  仮想環境($VENV_DIR)も削除する(config.toml は削除しない)"
      exit 0 ;;
    *) echo "不明なオプションです: $1" >&2; exit 1 ;;
  esac
done

echo "+ claude mcp remove --scope $SCOPE $NAME"
claude mcp remove --scope "$SCOPE" "$NAME"

if [ "$REMOVE_VENV" = 1 ] && [ -d "$VENV_DIR" ]; then
  echo "+ rm -rf $VENV_DIR"
  rm -rf "$VENV_DIR"
fi
echo "登録を解除しました。"
