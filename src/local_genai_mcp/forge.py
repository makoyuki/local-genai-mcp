import base64
import io
import json
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image as PILImage

from ._http import ApiClient
from .config import ForgeConfig


class ForgeClient(ApiClient):
    service_name = "Forge Neo"

    def __init__(self, cfg: ForgeConfig, transport: httpx.AsyncBaseTransport | None = None):
        auth = (cfg.username, cfg.password) if cfg.username else None
        super().__init__(cfg.base_url, cfg.timeout_seconds, auth=auth, transport=transport)
        self.cfg = cfg
        port = httpx.URL(cfg.base_url).port or 7860
        self.connect_hint = (
            "Forge Neoが起動しているか、webui-user.bat の COMMANDLINE_ARGS に --api --listen を付けているか、"
            f"WindowsのファイアウォールでTCP {port}番が許可されているかを確認してください。"
        )

    def not_found_hint(self, path: str) -> str:
        if path.startswith("/sdapi/"):
            return "APIが有効になっていない可能性があります。COMMANDLINE_ARGS に --api を付けて起動してください。"
        return ""

    async def options(self) -> dict:
        return await self.request("GET", "/sdapi/v1/options")

    async def checkpoints(self) -> list[dict]:
        return await self.request("GET", "/sdapi/v1/sd-models")

    async def loras(self) -> list[dict]:
        return await self.request("GET", "/sdapi/v1/loras")

    async def samplers(self) -> list[dict]:
        return await self.request("GET", "/sdapi/v1/samplers")

    async def upscalers(self) -> list[dict]:
        return await self.request("GET", "/sdapi/v1/upscalers", allow_404=True) or []

    async def schedulers(self) -> list[dict]:
        return await self.request("GET", "/sdapi/v1/schedulers", allow_404=True) or []

    async def txt2img(self, payload: dict) -> dict:
        return await self.request("POST", "/sdapi/v1/txt2img", json=payload)


def count_terms(text: str) -> int:
    """ネガティブプロンプトの語数(カンマ区切りの項目数)。"""
    return sum(1 for t in text.split(",") if t.strip())


def merge_negative(default: str, extra: str | None, use_default: bool = True) -> str:
    """既定のネガティブ(config.toml)に、その回だけの追加分を書き足す。
    use_default=False のときだけ既定値を外し、追加分のみにする。"""
    parts = [default.strip().rstrip(",")] if use_default else []
    parts.append((extra or "").strip().strip(","))
    return ", ".join(p for p in parts if p)


def build_txt2img_payload(
    cfg: ForgeConfig,
    *,
    prompt: str,
    negative_prompt: str | None = None,
    use_default_negative: bool = True,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    seed: int = -1,
    batch_size: int = 1,
    checkpoint: str = "",
    hires: bool | None = None,
    hr_scale: float | None = None,
    hr_upscaler: str | None = None,
    denoising_strength: float | None = None,
) -> dict:
    d = cfg.defaults
    payload = {
        "prompt": prompt,
        "negative_prompt": merge_negative(d.negative_prompt, negative_prompt, use_default_negative),
        "width": width or d.width,
        "height": height or d.height,
        "steps": steps or d.steps,
        "cfg_scale": d.cfg_scale if cfg_scale is None else cfg_scale,
        "sampler_name": sampler_name or d.sampler_name,
        "seed": seed,
        "batch_size": batch_size,
        "n_iter": 1,
        "send_images": True,
        "save_images": False,
    }
    if scheduler or d.scheduler:
        payload["scheduler"] = scheduler or d.scheduler
    if d.enable_hr if hires is None else hires:
        payload["enable_hr"] = True
        payload["hr_scale"] = hr_scale or d.hr_scale
        payload["hr_upscaler"] = hr_upscaler or d.hr_upscaler
        payload["denoising_strength"] = d.denoising_strength if denoising_strength is None else denoising_strength
        payload["hr_second_pass_steps"] = d.hr_second_pass_steps
        # Forge Neo の API では、以下を省略すると Hires.fix が失敗する(None のまま扱われてエラー)/
        # 2回目の CFG が 1 になる。画面の既定(Use same choices、1回目と同じ CFG)に合わせる
        payload["hr_additional_modules"] = ["Use same choices"]
        payload["hr_cfg"] = payload["cfg_scale"]
    if checkpoint:
        payload["override_settings"] = {"sd_model_checkpoint": checkpoint}
        payload["override_settings_restore_afterwards"] = False
    return payload


def parse_seeds(response: dict, count: int) -> list[int | None]:
    try:
        info = json.loads(response.get("info") or "{}")
    except (TypeError, ValueError):
        info = {}
    seeds = info.get("all_seeds") or ([info["seed"]] if "seed" in info else [])
    if len(seeds) < count:
        seeds = list(seeds) + [None] * (count - len(seeds))
    return seeds[:count]


def decode_image(b64: str) -> bytes:
    if "," in b64[:100]:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


def save_images(images: list[bytes], seeds: list[int | None], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    paths = []
    for i, (data, seed) in enumerate(zip(images, seeds)):
        name = f"{stamp}_{seed if seed is not None else 'noseed'}_{i}.png"
        path = out_dir / name
        path.write_bytes(data)
        paths.append(path)
    return paths


def make_preview(data: bytes, max_size: int) -> bytes:
    with PILImage.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((max_size, max_size))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
