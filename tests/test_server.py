import base64
import io
import json

import httpx
import pytest
from mcp import Client
from PIL import Image as PILImage

from local_genai_mcp.config import Config, ForgeConfig, OllamaConfig
from local_genai_mcp.server import build_error_server, build_server

OLLAMA_URL = "http://ollama.test:11434"
FORGE_URL = "http://forge.test:7860"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def png_b64(color=(200, 50, 50)) -> str:
    buf = io.BytesIO()
    PILImage.new("RGB", (64, 64), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeServices:
    def __init__(self, *, forge_api_enabled=True):
        self.requests: list[httpx.Request] = []
        self.forge_api_enabled = forge_api_enabled

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "ollama.test":
            if path == "/api/version":
                return httpx.Response(200, json={"version": "0.12.0"})
            if path == "/api/tags":
                return httpx.Response(200, json={"models": [
                    {"name": "gemma3:12b", "size": 8 * 1024**3, "details": {"parameter_size": "12B", "quantization_level": "Q4_K_M"}},
                ]})
            if path == "/api/ps":
                return httpx.Response(200, json={"models": [{"name": "gemma3:12b"}]})
            if path == "/api/chat":
                body = json.loads(request.content)
                return httpx.Response(200, json={
                    "model": body["model"],
                    "message": {"role": "assistant", "content": "こんにちは"},
                    "total_duration": 1_500_000_000,
                })
        if request.url.host == "forge.test" and self.forge_api_enabled:
            if path == "/sdapi/v1/options":
                return httpx.Response(200, json={"sd_model_checkpoint": "pony.safetensors"})
            if path == "/sdapi/v1/sd-models":
                return httpx.Response(200, json=[{"title": "pony.safetensors [abc123]", "model_name": "pony"}])
            if path == "/sdapi/v1/loras":
                return httpx.Response(200, json=[{"name": "styleA"}])
            if path == "/sdapi/v1/samplers":
                return httpx.Response(200, json=[{"name": "Euler a"}, {"name": "DPM++ 2M"}])
            if path == "/sdapi/v1/upscalers":
                return httpx.Response(200, json=[{"name": "None"}, {"name": "ESRGAN_4x"}])
            if path == "/sdapi/v1/txt2img":
                body = json.loads(request.content)
                n = body["batch_size"]
                seeds = [1000 + i for i in range(n)]
                return httpx.Response(200, json={
                    "images": [png_b64() for _ in range(n)],
                    "parameters": body,
                    "info": json.dumps({"seed": seeds[0], "all_seeds": seeds}),
                })
        return httpx.Response(404, text="Not Found")

    def last(self, path: str) -> httpx.Request:
        return next(r for r in reversed(self.requests) if r.url.path == path)


def make_config(tmp_path, **ollama_kw) -> Config:
    return Config(
        ollama=OllamaConfig(base_url=OLLAMA_URL, **ollama_kw),
        forge=ForgeConfig(base_url=FORGE_URL, output_dir=str(tmp_path / "out")),
        source=tmp_path / "config.toml",
    )


def text_of(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


@pytest.mark.anyio
async def test_lists_all_tools(tmp_path):
    server = build_server(make_config(tmp_path), transport=httpx.MockTransport(FakeServices()))
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {
        "check_connections", "usage_guide", "ollama_list_models", "ollama_chat",
        "forge_list_checkpoints", "forge_list_loras", "forge_list_samplers", "forge_txt2img",
    }


@pytest.mark.anyio
async def test_disabled_services_have_no_tools(tmp_path):
    config = make_config(tmp_path)
    config.ollama.enabled = False
    config.forge.enabled = False
    server = build_server(config, transport=httpx.MockTransport(FakeServices()))
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"check_connections", "usage_guide"}


@pytest.mark.anyio
async def test_usage_guide_and_help_prompt(tmp_path):
    config = make_config(tmp_path, default_model="qwen3.5:9b")
    config.forge.defaults.enable_hr = True
    server = build_server(config, transport=httpx.MockTransport(FakeServices()))
    async with Client(server) as client:
        guide = text_of(await client.call_tool("usage_guide", {}))
        prompts = (await client.list_prompts()).prompts
        msgs = (await client.get_prompt("help")).messages
    assert "既定のモデル: qwen3.5:9b" in guide and "思考(think): 既定はオフ" in guide
    assert "1024x1024" in guide and "仕上がり 2048x2048" in guide and "縦長で" in guide
    assert [p.name for p in prompts] == ["help"]
    assert "local-genai の使い方" in msgs[0].content.text


def test_guide_omits_disabled_services(tmp_path):
    from local_genai_mcp.guide import build_guide
    config = make_config(tmp_path)
    config.ollama.enabled = False
    text = build_guide(config)
    assert "Ollama" not in text and "Forge Neo" in text


@pytest.mark.anyio
async def test_check_connections(tmp_path):
    server = build_server(make_config(tmp_path), transport=httpx.MockTransport(FakeServices()))
    async with Client(server) as client:
        text = text_of(await client.call_tool("check_connections", {}))
    assert "[OK] Ollama" in text and "モデル 1個" in text
    assert "[OK] Forge Neo" in text and "pony.safetensors" in text


@pytest.mark.anyio
async def test_ollama_chat_uses_default_model_and_system(tmp_path):
    fake = FakeServices()
    server = build_server(make_config(tmp_path, default_model="gemma3:12b", keep_alive="5m"), transport=httpx.MockTransport(fake))
    async with Client(server) as client:
        result = await client.call_tool("ollama_chat", {"prompt": "やあ", "system": "丁寧に", "temperature": 0.3})
    assert "こんにちは" in text_of(result)
    body = json.loads(fake.last("/api/chat").content)
    assert body["model"] == "gemma3:12b"
    assert body["messages"][0] == {"role": "system", "content": "丁寧に"}
    assert body["options"] == {"temperature": 0.3}
    assert body["keep_alive"] == "5m"
    assert body["stream"] is False
    assert body["think"] is False


@pytest.mark.anyio
async def test_ollama_chat_think_and_model_can_be_chosen(tmp_path):
    fake = FakeServices()
    server = build_server(make_config(tmp_path, default_model="gemma3:12b"), transport=httpx.MockTransport(fake))
    async with Client(server) as client:
        result = await client.call_tool("ollama_chat", {"prompt": "やあ", "model": "llama3.1:8b", "think": True})
    assert "model: llama3.1:8b" in text_of(result)
    body = json.loads(fake.last("/api/chat").content)
    assert body["model"] == "llama3.1:8b" and body["think"] is True


@pytest.mark.anyio
async def test_ollama_chat_without_model_lists_available(tmp_path):
    server = build_server(make_config(tmp_path), transport=httpx.MockTransport(FakeServices()))
    async with Client(server) as client:
        result = await client.call_tool("ollama_chat", {"prompt": "やあ"})
    assert result.is_error
    assert "gemma3:12b" in text_of(result)


@pytest.mark.anyio
async def test_forge_txt2img_saves_and_previews(tmp_path):
    fake = FakeServices()
    server = build_server(make_config(tmp_path), transport=httpx.MockTransport(fake))
    async with Client(server) as client:
        result = await client.call_tool("forge_txt2img", {"prompt": "1girl, <lora:styleA:0.8>", "batch_size": 2, "steps": 20})
    assert not result.is_error
    saved = sorted((tmp_path / "out").glob("*.png"))
    assert len(saved) == 2
    assert "_1000_0.png" in saved[0].name and "_1001_1.png" in saved[1].name
    text = text_of(result)
    assert str(saved[0]) in text and "seed 1000" in text
    assert sum(1 for c in result.content if c.type == "image") == 2

    body = json.loads(fake.last("/sdapi/v1/txt2img").content)
    assert body["prompt"] == "1girl, <lora:styleA:0.8>"
    assert body["steps"] == 20
    assert body["width"] == 1024 and body["sampler_name"] == "Euler a"
    assert "override_settings" not in body and "scheduler" not in body
    assert "enable_hr" not in body


@pytest.mark.anyio
async def test_forge_txt2img_hires(tmp_path):
    fake = FakeServices()
    config = make_config(tmp_path)
    config.forge.defaults.enable_hr = True
    server = build_server(config, transport=httpx.MockTransport(fake))
    async with Client(server) as client:
        result = await client.call_tool("forge_txt2img", {"prompt": "cat", "width": 832, "height": 1216})
        body = json.loads(fake.last("/sdapi/v1/txt2img").content)
        assert body["enable_hr"] is True and body["hr_scale"] == 2.0 and body["hr_upscaler"] == "ESRGAN_4x"
        assert body["denoising_strength"] == 0.4 and body["hr_second_pass_steps"] == 0
        assert body["hr_additional_modules"] == ["Use same choices"] and body["hr_cfg"] == body["cfg_scale"]
        assert "832x1216 → Hires.fix x2" in text_of(result) and "1664x2432" in text_of(result)

        await client.call_tool("forge_txt2img", {"prompt": "cat", "hr_scale": 1.5, "denoising_strength": 0.3})
        body = json.loads(fake.last("/sdapi/v1/txt2img").content)
        assert body["hr_scale"] == 1.5 and body["denoising_strength"] == 0.3

        await client.call_tool("forge_txt2img", {"prompt": "cat", "hires": False})
        body = json.loads(fake.last("/sdapi/v1/txt2img").content)
        assert "enable_hr" not in body


@pytest.mark.anyio
async def test_forge_txt2img_checkpoint_and_save_dir(tmp_path):
    fake = FakeServices()
    server = build_server(make_config(tmp_path), transport=httpx.MockTransport(fake))
    async with Client(server) as client:
        await client.call_tool("forge_txt2img", {
            "prompt": "cat", "checkpoint": "pony.safetensors [abc123]", "scheduler": "Karras",
            "save_dir": str(tmp_path / "custom"),
        })
    body = json.loads(fake.last("/sdapi/v1/txt2img").content)
    assert body["override_settings"] == {"sd_model_checkpoint": "pony.safetensors [abc123]"}
    assert body["override_settings_restore_afterwards"] is False
    assert body["scheduler"] == "Karras"
    assert len(list((tmp_path / "custom").glob("*.png"))) == 1


@pytest.mark.anyio
async def test_forge_list_tools(tmp_path):
    server = build_server(make_config(tmp_path), transport=httpx.MockTransport(FakeServices()))
    async with Client(server) as client:
        ckpts = text_of(await client.call_tool("forge_list_checkpoints", {}))
        loras = text_of(await client.call_tool("forge_list_loras", {}))
        samplers = text_of(await client.call_tool("forge_list_samplers", {}))
    assert "pony.safetensors [abc123] (使用中)" in ckpts
    assert "- styleA" in loras
    assert "DPM++ 2M" in samplers and "スケジューラ" not in samplers
    assert "- ESRGAN_4x" in samplers


@pytest.mark.anyio
async def test_forge_without_api_flag_gives_hint(tmp_path):
    server = build_server(make_config(tmp_path), transport=httpx.MockTransport(FakeServices(forge_api_enabled=False)))
    async with Client(server) as client:
        result = await client.call_tool("forge_list_loras", {})
    assert result.is_error
    assert "--api" in text_of(result)


@pytest.mark.anyio
async def test_error_server_explains_config_problem():
    server = build_error_server("設定ファイル(config.toml)が見つかりません。")
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        text = text_of(await client.call_tool("check_connections", {}))
    assert names == {"check_connections"}
    assert "config.toml" in text


@pytest.mark.anyio
async def test_connection_refused_gives_hint(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    server = build_server(make_config(tmp_path, default_model="gemma3:12b"), transport=httpx.MockTransport(refuse))
    async with Client(server) as client:
        chat = await client.call_tool("ollama_chat", {"prompt": "やあ"})
        check = text_of(await client.call_tool("check_connections", {}))
    assert chat.is_error and "OLLAMA_HOST" in text_of(chat)
    assert "[NG] Ollama" in check and "[NG] Forge Neo" in check and "--listen" in check
