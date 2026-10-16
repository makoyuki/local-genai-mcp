# local-genai-mcp

LAN内で動いているローカル生成AIを、Claude Code から使えるようにするMCPサーバです。

- **Ollama**(ローカルLLM): モデル一覧、文章生成
- **Stable Diffusion WebUI Forge Neo**(WebUI1111互換API): チェックポイント・LoRA・サンプラーの一覧、画像生成(txt2img)

Claude Code に「Ollamaの gemma3:12b でこの文章を要約して」「Forge Neoで夕焼けの海辺の猫を1枚描いて」のように頼むと、このMCPサーバ経由で各サービスを呼び出します。

## 構成の例

```
[Ubuntu] Claude Code ──(stdio)── local-genai-mcp ──(HTTP)──┬─ [Windows] Ollama     :11434
                                                            └─ [Windows] Forge Neo  :7860
```

MCPサーバは Claude Code と同じマシンで動き、Ollama や Forge Neo へは LAN 越しに HTTP でアクセスします。生成した画像は、MCPサーバ側のマシンのフォルダ(既定では `~/ai-studio/repo/genai-outputs/forge`)に保存されます。

## 使えるツール

| ツール | 内容 |
|---|---|
| `check_connections` | 設定されている各サービスに接続できるかを確認する |
| `usage_guide` | 使い方・頼み方の例と、現在の既定値を返す |
| `ollama_list_models` | Ollama のモデル一覧(読み込み中のものに印) |
| `ollama_chat` | Ollama のモデルに指示を送り、応答の文章を返す(会話の履歴は保持しない)。モデル(`model`)や思考の有無(`think`)を1回ごとに指定できる |
| `forge_list_checkpoints` | Forge Neo のチェックポイント一覧と、現在のモデル |
| `forge_list_loras` | Forge Neo の LoRA 一覧 |
| `forge_list_samplers` | Forge Neo のサンプラー・スケジューラ・アップスケーラ(Hires.fix用)一覧 |
| `forge_txt2img` | 画像を生成して PNG で保存し、パスとシード値、縮小プレビューを返す。サイズ、Hires.fix、チェックポイント、追加のネガティブを1回ごとに指定できる(既定のネガティブは毎回自動で付く) |

`forge_txt2img` のプロンプトには、WebUI1111 と同じ書き方(`(word:1.2)` の強調、`<lora:名前:重み>`)が使えます。

画像の大きさは、`width` x `height`(既定 1024x1024)で描いてから、Hires.fix で `hr_scale` 倍(既定 2倍、`ESRGAN_4x`)に拡大して描き直します。既定値は `config.toml` の `[forge.defaults]` で変えられ、Claude Code に「縦長で」「Hires.fixなしで」「1.5倍で」のように頼めば、1回ごとの指定もできます。

`checkpoint` を指定すると、Forge Neo 側で選ばれているモデルも切り替わったままになります(続けて同じモデルで生成するときに、読み込み直しを避けるため)。

### ネガティブプロンプト

- `config.toml` の `[forge.defaults]` の `negative_prompt` は、MCPサーバが**毎回自動で付けて**送ります。Claude の判断や会話を通らないので、書き忘れや言い換えで抜けることはありません。
- 望ましくない画像(NSFW など)を避けるための語は、ここにまとめておく使い方を想定しています。その語を会話やプロンプトに毎回書く必要はありません。
- ツールの引数 `negative_prompt` は「その回だけの追加分」で、既定のネガティブの後ろに書き足されます。
- 既定のネガティブを外したいときだけ、`use_default_negative=false` を指定します。Claude には「ユーザーがはっきり頼んだときだけ外す」よう指示しています(サーバの説明文とガイド)。
- 生成結果とガイドには、既定のネガティブの**語数だけ**を表示し、文言そのものは表示しません。
- 既定のネガティブを入れても、モデルによっては望ましくない方向に寄ることがあります(Pony 系など)。その場合はモデルを変えるか、Forge Neo の画面で直接生成してください。

## 使い方のヘルプ

使い方と頼み方の例(現在の既定値入り)は、次のどれかで確認できます。

- Claude Code の会話中に `/mcp__local-genai__help` と入力する(MCP のプロンプト機能。`/` を入力すると候補に出る)
- Claude Code に「local-genai の使い方を教えて」と頼む(`usage_guide` ツールが使われる)
- ターミナルで `local-genai-mcp --guide` を実行する(下の「うまく動かないとき」のコマンドの `--check` を `--guide` に変える)

## 必要なもの

- Claude Code を使うマシン: Linux(Ubuntu で確認)。Python は uv が自動で用意します
- Ollama 側: 環境変数 `OLLAMA_HOST=0.0.0.0:11434` を設定して起動(別のマシンから使う場合)
- Forge Neo 側: `webui-user.bat` の `COMMANDLINE_ARGS` に `--api --listen` を付けて起動
- Windows 側のファイアウォールで、各ポート(11434、7860 など)への接続を許可

## セットアップ

```bash
cd ~/ai-studio/repo/local-genai-mcp
./install.sh
```

`install.sh` が行うこと:

1. uv がなければ、確認のうえ公式スクリプトでインストール
2. 依存ライブラリのインストール(仮想環境は `~/.local/share/local-genai-mcp/venv`。このフォルダが NAS 上にあっても、仮想環境はローカルのディスクに置く)
3. `config.toml` がなければ `config.example.toml` からコピー
4. `config.toml` があれば接続確認(`--check`)
5. Claude Code に `local-genai` という名前で登録(既定は `--scope user` = どのフォルダで起動した Claude Code からも使える)

初回は `config.toml` が作られた時点で、書き換えを促すメッセージが出ます。`config.toml` を編集してから、接続確認をしてください。

```bash
UV_PROJECT_ENVIRONMENT=~/.local/share/local-genai-mcp/venv uv run --project . --no-dev local-genai-mcp --check
```

主なオプション(`./install.sh --help` で一覧):

- `--no-register`: 依存関係の準備と接続確認だけ行い、Claude Code には登録しない
- `--dry-run`: 実行するコマンドを表示するだけ
- `--scope project`: 今いるフォルダの `.mcp.json` に登録する(そのフォルダで起動したときだけ使える)

登録できたかは、Claude Code を起動し直して、会話中に `/mcp` と入力すると確認できます。

## 設定ファイル(config.toml)

`config.example.toml` に説明付きで全項目があります。主な項目:

```toml
[ollama]
base_url = "http://192.168.0.10:11434"   # Ollama のアドレス
default_model = "qwen3.5:9b"             # モデル名を省略したときに使う
think = false                            # 思考対応モデルで考える過程を使うか(使うと遅い)

[forge]
base_url = "http://192.168.0.20:7860"    # Forge Neo のアドレス
output_dir = "~/ai-studio/repo/genai-outputs/forge"   # 画像の保存先
preview = true                           # 縮小プレビューを Claude に返すか

[forge.defaults]                         # 画像生成の既定値
width = 1024
height = 1024
steps = 25
cfg_scale = 7.0
sampler_name = "Euler a"
enable_hr = true                         # Hires.fix を使うか
hr_scale = 2.0                           # Hires.fix の倍率
hr_upscaler = "ESRGAN_4x"                # アップスケーラ(forge_list_samplers で確認)
denoising_strength = 0.4                 # 描き直す強さ
```

- 使わないサービスは `enabled = false` にすると、そのツール自体が表示されなくなります
- Forge Neo を `--api-auth ユーザー名:パスワード` 付きで起動している場合は `username` / `password` を設定します
- `config.toml` には実際のアドレスや認証情報が入るので、Git の管理対象外にしています(`.gitignore`)
- 設定ファイルは、環境変数 `LOCAL_GENAI_MCP_CONFIG` → このフォルダの `config.toml` → `~/.config/local-genai-mcp/config.toml` の順に探します(`local-genai-mcp --print-config-paths` で確認できます)
- 設定を書き換えたら、Claude Code を起動し直すと反映されます

## HTTP で動かす(LibreChat などから使う)

書籍の執筆後に追加した使い方です。Claude Code から使う場合(stdio)は、これまでどおりで何も変わりません。

`--http` を付けると、stdio ではなく HTTP(streamable-http)で待ち受けます。Docker で動いている LibreChat のように、Claude Code 以外の MCP クライアントから使うときのためのものです。

```bash
UV_PROJECT_ENVIRONMENT=~/.local/share/local-genai-mcp/venv uv run --project . --no-dev local-genai-mcp \
  --http --host 172.17.0.1 --port 8765 --allow-host host.docker.internal
```

- 接続先の URL は `http://<アドレス>:<ポート>/mcp` です(上の例で Docker のコンテナから使う場合は `http://host.docker.internal:8765/mcp`)
- `--host` の既定は `127.0.0.1`(同じマシンからだけ使える)、`--port` の既定は `8765` です。`172.17.0.1` は Docker の既定のブリッジ(`docker0`)のアドレスで、こうするとコンテナからは使え、LAN の他のマシンからは届きません
- 受け付ける `Host` ヘッダは、`127.0.0.1`・`localhost`・`--host` のアドレスと、`--allow-host` で足した名前だけです(DNS リバインディング対策)。それ以外は 421 で断ります
- HTTP 版には認証がありません。`--host 0.0.0.0` のように LAN 全体に公開するのは、信頼できるネットワークの中だけにしてください
- 生成した画像は、HTTP 版でも MCP サーバを動かしているマシンのフォルダに保存されます

LibreChat の `librechat.yaml` に登録する例:

```yaml
mcpServers:
  local-genai:
    type: streamable-http
    url: http://host.docker.internal:8765/mcp
    timeout: 600000   # 画像生成は数分かかることがあるので長めに(ミリ秒)
    serverInstructions: true  # サーバの説明文(ネガティブプロンプトの扱いなど)をモデルに渡す

mcpSettings:
  # LibreChat は既定でプライベートアドレスへの接続を断るので、この宛先だけ許可する
  allowedDomains:
    - "host.docker.internal"
  allowedAddresses:
    - "host.docker.internal:8765"
```

## 登録の解除

```bash
./uninstall.sh                 # Claude Code への登録を解除
./uninstall.sh --remove-venv   # 仮想環境も削除(config.toml は残す)
```

## うまく動かないとき

まず接続確認を実行すると、つながらない理由が表示されます。

```bash
UV_PROJECT_ENVIRONMENT=~/.local/share/local-genai-mcp/venv uv run --project . --no-dev local-genai-mcp --check
```

- **Ollama に接続できない**: Ollama 側で `OLLAMA_HOST=0.0.0.0:11434` を設定して起動し直したか、ファイアウォールで 11434 番を許可したか
- **Forge Neo に接続できない**: `--listen` を付けたか、ファイアウォールで 7860 番(`--port` で変えた場合はその番号)を許可したか
- **Forge Neo の /sdapi/... が 404**: `--api` を付け忘れている
- **認証エラー(401)**: `--api-auth` を使っている場合は `config.toml` の `username` / `password`
- **画像生成がタイムアウトする**: `config.toml` の `[forge]` の `timeout_seconds` を増やす(大きいモデルの初回読み込みは時間がかかる)
- 接続の確立は5秒で打ち切るので、アドレスの間違いなどはすぐに分かります

## 開発

```bash
uv sync                # 開発用(pytest)も含めてインストール
uv run pytest          # テスト(実際の Ollama / Forge Neo は不要。HTTP の応答を模擬している)
```

MCP の Python SDK は 2.x 系を使っています(`mcp.server.mcpserver.MCPServer`)。1.x 系の `FastMCP` とは書き方が異なります。

## 未対応・今後の候補

- img2img、ComfyUI、音声合成(Irodori-TTS)などは未対応

## ライセンス

MIT License(`LICENSE` を参照)。依存ライブラリ(mcp: MIT、httpx: BSD-3-Clause、Pillow: MIT-CMU ほか)はいずれも MIT と両立する許諾条件で、このリポジトリには同梱していません(インストール時に uv が取得します)。
