# local-genai-mcp

Claude Code から LAN 内のローカル生成AI(Ollama、Forge Neo)を使うための MCP サーバ。使い方は README.md。

## 構成

- `src/local_genai_mcp/server.py`: ツール定義(`build_server`)、設定エラー時の最小サーバ(`build_error_server`)、CLI(`main`: `--check`、`--print-config-paths`、`--guide`)
- `src/local_genai_mcp/_http.py`: 共通の HTTP 処理。接続エラー・404・401 などを日本語の分かりやすいメッセージの `ServiceError` に変換する
- `src/local_genai_mcp/ollama.py` / `forge.py`: 各サービスの API クライアント。`forge.py` には txt2img のペイロード組み立て、画像の保存・プレビュー作成もある
- `src/local_genai_mcp/guide.py`: 使い方・頼み方のガイド(`usage_guide` ツール、`help` プロンプト = `/mcp__local-genai__help`、`--guide` で共通)。ツールや既定値を変えたらここも直す
- `src/local_genai_mcp/config.py`: `config.toml` の読み込み(未知の項目はエラーにする)

## 守ること

- MCP の Python SDK は **2.x 系**(`from mcp.server.mcpserver import MCPServer, Image`、エラーは `mcp.server.mcpserver.exceptions.ToolError`)。1.x の `FastMCP` の書き方にしない
- stdio で通信するため、標準出力には何も print しない(`--check` などの CLI モードを除く)。ログは標準エラーへ
- ツール内で想定できる失敗は `ToolError` にする(`_run()` が `ServiceError` を変換する)。それ以外の例外はモデルに中身が見えない
- `config.toml` には実際の IP アドレスや認証情報が入るので、コミットしない(`.gitignore` 済み)。例のアドレスは `config.example.toml` に書く
- Forge Neo の txt2img で Hires.fix を使うときは `hr_additional_modules` を必ず送る(省略すると HTTP 500)。`hr_cfg` は省略すると 1 になるので `cfg_scale` と同じ値を送る
- テストは実サービスなしで動くように、`httpx.MockTransport` で HTTP の応答を模擬し、`mcp.Client(server)` でプロセス内から呼ぶ

## テスト

```bash
uv sync
uv run pytest
```
