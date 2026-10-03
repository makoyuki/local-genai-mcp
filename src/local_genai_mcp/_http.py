from typing import Any

import httpx

CONNECT_TIMEOUT_SECONDS = 5.0


class ServiceError(Exception):
    pass


class ApiClient:
    service_name = ""
    connect_hint = ""

    def __init__(
        self,
        base_url: str,
        timeout: float,
        auth: tuple[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.auth = auth
        self._transport = transport

    def not_found_hint(self, path: str) -> str:
        return ""

    async def request(self, method: str, path: str, *, allow_404: bool = False, **kwargs) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=CONNECT_TIMEOUT_SECONDS),
                auth=self.auth,
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ServiceError(f"{self.service_name}({self.base_url})に接続できません。{self.connect_hint}") from e
        except httpx.TimeoutException as e:
            raise ServiceError(
                f"{self.service_name}({self.base_url})からの応答が{self.timeout:g}秒以内に返ってきませんでした。"
                "処理が重い場合は config.toml の timeout_seconds を増やしてください。"
            ) from e
        except httpx.HTTPError as e:
            raise ServiceError(f"{self.service_name}との通信でエラーが発生しました: {e}") from e

        if response.status_code == 404 and allow_404:
            return None
        if response.status_code == 401:
            raise ServiceError(f"{self.service_name}の認証に失敗しました(HTTP 401)。config.toml の username/password を確認してください。")
        if response.status_code == 404:
            raise ServiceError(f"{self.service_name}に {path} がありません(HTTP 404)。{self.not_found_hint(path)}")
        if response.status_code >= 400:
            raise ServiceError(f"{self.service_name}がエラーを返しました(HTTP {response.status_code}): {response.text[:500]}")
        try:
            return response.json()
        except ValueError as e:
            raise ServiceError(f"{self.service_name}の応答がJSONではありません: {response.text[:200]}") from e
