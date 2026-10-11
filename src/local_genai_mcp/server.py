import argparse
import asyncio
import logging
import sys
import tomllib
from pathlib import Path
from typing import Annotated

import httpx
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ._http import ServiceError
from .config import Config, candidate_paths, load_config
from .guide import build_guide
from .forge import (
    ForgeClient,
    build_txt2img_payload,
    count_terms,
    decode_image,
    make_preview,
    parse_seeds,
    save_images,
)
from .ollama import OllamaClient

SERVER_NAME = "local-genai"
MAX_PREVIEWS = 4

INSTRUCTIONS = """\
LAN内で動いているローカル生成AIを使うためのツール群です。
- Ollama(ローカルLLM): ollama_list_models でモデルを確認し、ollama_chat で文章を生成します。
- Forge Neo(Stable Diffusion WebUI互換の画像生成): forge_txt2img で画像を生成します。
  サイズ・Hires.fix(拡大して描き直す処理)の既定値は config.toml にあり、引数で1回ごとに変えられます。
  config.toml の既定のネガティブプロンプトは毎回自動で付きます。negative_prompt にはその回だけ足したい語だけを渡し、
  既定値を外す(use_default_negative=false)のはユーザーがはっきり頼んだときだけにしてください。
  生成には数十秒から数分かかります。画像はMCPサーバ側のフォルダにPNGで保存され、パスが返ります。
使い方や頼み方を聞かれたら usage_guide の内容をもとに答えてください。
うまく動かないときは、まず check_connections で接続状況を確認してください。"""


def _gb(n: int | None) -> str:
    return f"{n / 1024**3:.1f}GB" if n else "?"


def _same_checkpoint(title: str, current: str) -> bool:
    # sd-models の title は「名前 [ハッシュ]」、options の sd_model_checkpoint はハッシュなしのことがある
    strip = lambda s: s.split(" [", 1)[0]
    return bool(current) and strip(title) == strip(current)


async def _run(coro):
    try:
        return await coro
    except ServiceError as e:
        raise ToolError(str(e)) from e


async def connection_report(config: Config, ollama: OllamaClient, forge: ForgeClient) -> tuple[str, bool]:
    lines = []
    ok = True
    if config.ollama.enabled:
        try:
            version = await ollama.version()
            models = await ollama.list_models()
            lines.append(f"[OK] Ollama {config.ollama.base_url} (version {version}, モデル {len(models)}個)")
        except ServiceError as e:
            ok = False
            lines.append(f"[NG] Ollama {config.ollama.base_url}: {e}")
    else:
        lines.append("[--] Ollama: 無効(config.toml で enabled = false)")

    if config.forge.enabled:
        try:
            opts = await forge.options()
            ckpts = await forge.checkpoints()
            current = opts.get("sd_model_checkpoint", "?")
            lines.append(f"[OK] Forge Neo {config.forge.base_url} (現在のモデル: {current}, チェックポイント {len(ckpts)}個)")
        except ServiceError as e:
            ok = False
            lines.append(f"[NG] Forge Neo {config.forge.base_url}: {e}")
    else:
        lines.append("[--] Forge Neo: 無効(config.toml で enabled = false)")
    return "\n".join(lines), ok


def build_server(config: Config, transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    mcp = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)
    ollama = OllamaClient(config.ollama, transport)
    forge = ForgeClient(config.forge, transport)

    @mcp.tool()
    async def check_connections() -> str:
        """設定されているローカル生成AI(Ollama、Forge Neo)に接続できるかを確認し、状況を返す。"""
        text, _ = await connection_report(config, ollama, forge)
        return f"設定ファイル: {config.source}\n{text}"

    @mcp.tool()
    async def usage_guide() -> str:
        """local-genai の使い方(モデルの選び方、画像の大きさやHires.fixの指定方法、頼み方の例、
        現在の既定値)を返す。使い方を聞かれたときに使う。"""
        return build_guide(config)

    @mcp.prompt(name="help", title="local-genai の使い方", description="ローカル生成AI(Ollama、Forge Neo)の使い方と頼み方の例を表示する")
    def help_prompt() -> str:
        return (
            "以下は local-genai(ローカル生成AIのMCPサーバ)の使い方のガイドです。"
            "この内容を、見出しと箇条書きのまま日本語で表示してください(要約や補足は不要です)。\n\n"
            + build_guide(config)
        )

    if config.ollama.enabled:

        @mcp.tool()
        async def ollama_list_models() -> str:
            """Ollamaにダウンロード済みのモデルの一覧と、現在メモリに読み込まれているモデルを返す。"""
            models = await _run(ollama.list_models())
            running = {m.get("name") for m in await _run(ollama.running_models())}
            if not models:
                return "モデルがありません。Ollama側で ollama pull <モデル名> を実行してください。"
            lines = []
            for m in models:
                details = m.get("details", {})
                mark = " (読み込み中)" if m.get("name") in running else ""
                lines.append(
                    f"- {m.get('name')}: {_gb(m.get('size'))}, "
                    f"{details.get('parameter_size', '?')}, {details.get('quantization_level', '?')}{mark}"
                )
            default = config.ollama.default_model or "(未設定)"
            return f"既定のモデル: {default}\n" + "\n".join(lines)

        @mcp.tool()
        async def ollama_chat(
            prompt: Annotated[str, Field(description="ローカルLLMに送る指示・質問")],
            model: Annotated[str, Field(description="使うモデル名(省略時は config.toml の default_model)")] = "",
            system: Annotated[str, Field(description="システムプロンプト(役割や口調の指定など。省略可)")] = "",
            temperature: Annotated[float | None, Field(description="生成のランダムさ(0〜2程度。省略時はモデルの既定値)")] = None,
            think: Annotated[bool | None, Field(description="思考(thinking)対応モデルで、答える前に考える過程を使うか。"
                                                       "使うと遅くなるが込み入った問いに強い(省略時は config.toml の think)")] = None,
        ) -> str:
            """Ollamaのローカルモデルに1回分の指示を送り、応答の文章を返す。下訳・要約・アイデア出しなど、
            ローカルで処理したい文章生成に使う。会話の履歴は保持しない。
            モデルは ollama_list_models で確認し、用途に合わせて model で指定できる。"""
            data = await _run(ollama.chat(prompt, model=model, system=system, temperature=temperature, think=think))
            content = data.get("message", {}).get("content", "")
            seconds = (data.get("total_duration") or 0) / 1e9
            return f"{content}\n\n(model: {data.get('model', model)}, {seconds:.1f}秒)"

    if config.forge.enabled:

        @mcp.tool()
        async def forge_list_checkpoints() -> str:
            """Forge Neoで使えるチェックポイント(画像生成モデル)の一覧と、現在使われているモデルを返す。"""
            opts = await _run(forge.options())
            ckpts = await _run(forge.checkpoints())
            current = opts.get("sd_model_checkpoint", "")
            lines = [f"- {c.get('title')}{' (使用中)' if _same_checkpoint(c.get('title', ''), current) else ''}" for c in ckpts]
            return f"現在のモデル: {current or '?'}\n" + "\n".join(lines)

        @mcp.tool()
        async def forge_list_loras() -> str:
            """Forge Neoで使えるLoRAの一覧を返す。プロンプトに <lora:名前:重み> と書くと使える。"""
            loras = await _run(forge.loras())
            if not loras:
                return "LoRAが見つかりません。"
            return "\n".join(f"- {l.get('name')}" for l in loras)

        @mcp.tool()
        async def forge_list_samplers() -> str:
            """Forge Neoで使えるサンプラー名、スケジューラ名、Hires.fix用のアップスケーラ名の一覧を返す。"""
            samplers = await _run(forge.samplers())
            schedulers = await _run(forge.schedulers())
            upscalers = await _run(forge.upscalers())
            text = "サンプラー:\n" + "\n".join(f"- {s.get('name')}" for s in samplers)
            if schedulers:
                text += "\nスケジューラ:\n" + "\n".join(f"- {s.get('label') or s.get('name')}" for s in schedulers)
            if upscalers:
                text += "\nアップスケーラ(Hires.fix用):\n" + "\n".join(f"- {u.get('name')}" for u in upscalers)
            return text

        @mcp.tool()
        async def forge_txt2img(
            prompt: Annotated[str, Field(description="プロンプト。WebUI1111と同じ書き方((word:1.2)の強調、<lora:名前:重み>)が使える")],
            negative_prompt: Annotated[str | None, Field(description="その回だけ追加するネガティブプロンプト。config.toml の既定のネガティブの後ろに"
                                                                    "書き足される(既定値は毎回自動で付くので、ここに書き写さなくてよい)")] = None,
            use_default_negative: Annotated[bool, Field(description="config.toml の既定のネガティブを付けるか。"
                                                                    "ユーザーがはっきり外すよう頼んだときだけ false にする")] = True,
            width: Annotated[int | None, Field(description="幅(Hires.fix前の大きさ。64の倍数を推奨。省略時は既定値)", ge=64, le=4096)] = None,
            height: Annotated[int | None, Field(description="高さ(Hires.fix前の大きさ。64の倍数を推奨。省略時は既定値)", ge=64, le=4096)] = None,
            steps: Annotated[int | None, Field(description="ステップ数", ge=1, le=150)] = None,
            cfg_scale: Annotated[float | None, Field(description="CFGスケール", ge=0, le=30)] = None,
            sampler_name: Annotated[str | None, Field(description="サンプラー名(forge_list_samplers で確認できる)")] = None,
            scheduler: Annotated[str | None, Field(description="スケジューラ名(省略時は既定値)")] = None,
            seed: Annotated[int, Field(description="シード値(-1でランダム)")] = -1,
            batch_size: Annotated[int, Field(description="一度に生成する枚数", ge=1, le=8)] = 1,
            checkpoint: Annotated[str, Field(description="使うチェックポイント名(forge_list_checkpoints の名前。省略時は現在のモデルのまま。"
                                                       "切り替えると Forge Neo 側の選択も切り替わったままになる)")] = "",
            hires: Annotated[bool | None, Field(description="Hires.fix(拡大して描き直し、細部をくっきりさせる)を使うか(省略時は既定値)")] = None,
            hr_scale: Annotated[float | None, Field(description="Hires.fixの倍率(例: 1.5、2)", ge=1, le=4)] = None,
            hr_upscaler: Annotated[str | None, Field(description="Hires.fixのアップスケーラ名(forge_list_samplers で確認できる)")] = None,
            denoising_strength: Annotated[float | None, Field(description="Hires.fixで描き直す強さ(0〜1。大きいほど元から変わる)", ge=0, le=1)] = None,
            save_dir: Annotated[str, Field(description="保存先フォルダ(省略時は config.toml の output_dir)")] = "",
        ) -> list[str | Image]:
            """Forge Neoで画像を生成(txt2img)し、PNGファイルとして保存して、保存先のパスとシード値を返す。
            config.toml で preview が有効なら、縮小したプレビュー画像も返す。"""
            payload = build_txt2img_payload(
                config.forge,
                prompt=prompt,
                negative_prompt=negative_prompt,
                use_default_negative=use_default_negative,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                sampler_name=sampler_name,
                scheduler=scheduler,
                seed=seed,
                batch_size=batch_size,
                checkpoint=checkpoint,
                hires=hires,
                hr_scale=hr_scale,
                hr_upscaler=hr_upscaler,
                denoising_strength=denoising_strength,
            )
            response = await _run(forge.txt2img(payload))
            images = [decode_image(b) for b in response.get("images", [])]
            if not images:
                raise ToolError("Forge Neoから画像が返ってきませんでした。")
            seeds = parse_seeds(response, len(images))
            out_dir = Path(save_dir).expanduser() if save_dir else config.forge.output_path
            paths = save_images(images, seeds, out_dir)

            size = f"{payload['width']}x{payload['height']}"
            if payload.get("enable_hr"):
                scale = payload["hr_scale"]
                size += (f" → Hires.fix x{scale:g}({payload['hr_upscaler']}, denoise {payload['denoising_strength']:g})"
                         f" = {round(payload['width'] * scale)}x{round(payload['height'] * scale)}")
            summary = [
                f"{len(paths)}枚生成しました({size}, "
                f"steps {payload['steps']}, cfg {payload['cfg_scale']}, {payload['sampler_name']})"
            ]
            default_n = count_terms(config.forge.defaults.negative_prompt) if use_default_negative else 0
            extra_n = count_terms(negative_prompt or "")
            if not use_default_negative:
                negative = f"既定のネガティブは外した(追加分 {extra_n}語)"
            elif default_n:
                negative = f"既定のネガティブ {default_n}語" + (f" + 追加 {extra_n}語" if extra_n else "")
            else:
                negative = "既定のネガティブなし(config.toml で未設定)" + (f"、追加 {extra_n}語" if extra_n else "")
            summary[0] += f"\nネガティブ: {negative}"
            summary += [f"- {p} (seed {s})" for p, s in zip(paths, seeds)]
            result: list[str | Image] = ["\n".join(summary)]
            if config.forge.preview:
                for data in images[:MAX_PREVIEWS]:
                    result.append(Image(data=make_preview(data, config.forge.preview_max_size), format="jpeg"))
            return result

    return mcp


def build_error_server(message: str) -> MCPServer:
    mcp = MCPServer(SERVER_NAME, instructions="設定に問題があり、ローカル生成AIは使えません。check_connections で理由を確認してください。")

    @mcp.tool()
    async def check_connections() -> str:
        """ローカル生成AIの設定・接続状況を返す(現在は設定エラー)。"""
        return f"設定エラーのため起動できませんでした:\n{message}"

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="local-genai-mcp", description="ローカル生成AI(Ollama、Forge Neo)用のMCPサーバ")
    parser.add_argument("--config", type=Path, help="設定ファイルのパス(省略時は自動で探す)")
    parser.add_argument("--check", action="store_true", help="接続確認だけを行って終了する")
    parser.add_argument("--print-config-paths", action="store_true", help="設定ファイルを探す場所を表示して終了する")
    parser.add_argument("--guide", action="store_true", help="使い方・頼み方のガイド(現在の既定値入り)を表示して終了する")
    args = parser.parse_args(argv)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.print_config_paths:
        for p in candidate_paths():
            print(f"{'[あり]' if p.is_file() else '[なし]'} {p}")
        return

    try:
        config = load_config(args.config)
    except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError) as e:
        if args.check or args.guide:
            print(f"設定エラー: {e}", file=sys.stderr)
            sys.exit(1)
        build_error_server(str(e)).run()
        return

    if args.guide:
        print(build_guide(config))
        return

    if args.check:
        text, ok = asyncio.run(connection_report(config, OllamaClient(config.ollama), ForgeClient(config.forge)))
        print(f"設定ファイル: {config.source}")
        print(text)
        sys.exit(0 if ok else 1)

    build_server(config).run()


if __name__ == "__main__":
    main()
