import httpx

from ._http import ApiClient, ServiceError
from .config import OllamaConfig


class OllamaClient(ApiClient):
    service_name = "Ollama"
    connect_hint = (
        "Ollamaが起動しているか、別のマシンから使う場合は環境変数 OLLAMA_HOST=0.0.0.0:11434 を設定して起動しているか、"
        "ファイアウォールでポートが許可されているかを確認してください。"
    )

    def __init__(self, cfg: OllamaConfig, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(cfg.base_url, cfg.timeout_seconds, transport=transport)
        self.cfg = cfg

    async def version(self) -> str:
        data = await self.request("GET", "/api/version")
        return data.get("version", "?")

    async def list_models(self) -> list[dict]:
        data = await self.request("GET", "/api/tags")
        return data.get("models", [])

    async def running_models(self) -> list[dict]:
        data = await self.request("GET", "/api/ps")
        return data.get("models", [])

    async def chat(
        self, prompt: str, model: str = "", system: str = "", temperature: float | None = None, think: bool | None = None
    ) -> dict:
        model = model or self.cfg.default_model
        if not model:
            names = [m.get("name", "") for m in await self.list_models()]
            raise ServiceError(
                "モデルが指定されていません。model を指定するか、config.toml の default_model を設定してください。"
                f"利用できるモデル: {', '.join(names) or '(なし)'}"
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": self.cfg.think if think is None else think,
        }
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        if self.cfg.keep_alive:
            payload["keep_alive"] = self.cfg.keep_alive
        return await self.request("POST", "/api/chat", json=payload)
