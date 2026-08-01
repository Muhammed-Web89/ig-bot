import hmac
import hashlib
import httpx
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.config import settings

logger = structlog.get_logger()
GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class MetaAPIError(Exception):
    """Meta API'den donen genel hatalar."""

    pass


class MetaRateLimitError(Exception):
    """Rate limit veya kullanim kotasi asim durumlari."""

    pass


class MetaClient:
    """Meta Graph API ile guvenli, retry destekli iletisim."""

    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or settings.meta_page_access_token
        self.client = httpx.AsyncClient(
            base_url=GRAPH_API_BASE,
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    def generate_appsecret_proof(self) -> str:
        """App Secret Proof uretir (token guvenligi icin onerilir)."""
        digest = hmac.new(
            settings.meta_app_secret.encode(),
            self.access_token.encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((MetaRateLimitError, httpx.NetworkError)),
        reraise=True,
    )
    async def _post(self, path: str, payload: dict) -> dict:
        params = {
            "access_token": self.access_token,
            "appsecret_proof": self.generate_appsecret_proof(),
        }
        response = await self.client.post(path, params=params, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "http_error",
                status=exc.response.status_code,
                body=exc.response.text,
            )
            raise MetaAPIError(
                f"HTTP {exc.response.status_code}: {exc.response.text}"
            )

        data = response.json()

        if "error" in data:
            code = data["error"].get("code")
            subcode = data["error"].get("error_subcode")
            message = data["error"].get("message", "Unknown error")
            logger.warning(
                "meta_api_error",
                code=code,
                subcode=subcode,
                message=message,
            )

            if code in (4, 17, 32, 613) or subcode in (2207001, 2207005):
                raise MetaRateLimitError(message)
            raise MetaAPIError(message)

        return data

    async def send_private_reply(self, comment_id: str, message: str) -> dict:
        """
        Bir yoruma yanit olarak DM gonderir (Private Reply).
        Endpoint: POST /{comment-id}/private_replies
        """
        payload = {"message": message}
        return await self._post(f"/{comment_id}/private_replies", payload)

    async def send_message(self, recipient_id: str, message: str) -> dict:
        """
        Mevcut bir konusmaya mesaj gonderir.
        Endpoint: POST /me/messages
        """
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message},
        }
        return await self._post("/me/messages", payload)

    async def get_followers_page(self, after_cursor: str | None = None) -> dict:
        """
        Instagram hesabinin takipcilerini sayfali olarak ceker.
        Not: Buyuk listelerde rate-limit dikkate alinmali.
        """
        fields = "id,username"
        url = f"/{settings.instagram_account_id}/followers"
        params = {
            "access_token": self.access_token,
            "appsecret_proof": self.generate_appsecret_proof(),
            "fields": fields,
            "limit": 100,
        }
        if after_cursor:
            params["after"] = after_cursor

        response = await self.client.get(url, params=params)
        data = response.json()
        if "error" in data:
            raise MetaAPIError(data["error"].get("message"))
        return data

    async def close(self):
        await self.client.aclose()
