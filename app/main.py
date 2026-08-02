import hmac
import hashlib
import json
import structlog
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings
from app.models import InstagramComment
from app.workers import process_comment_job

logger = structlog.get_logger()
app = FastAPI(title="Instagram Auto DM")


def _fingerprint(value: bytes | str, length: int = 12) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:length]


def verify_signature(
    payload: bytes,
    signature_256: str,
    signature_legacy: str = "",
) -> bool:
    """Meta webhook imzasini ham SHA256 hem de legacy SHA1 ile dogrular."""
    secret = settings.meta_app_secret.strip()
    secret_fingerprint = _fingerprint(secret)
    payload_fingerprint = _fingerprint(payload)

    if signature_256.startswith("sha256="):
        expected = signature_256.split("=", 1)[1].strip().lower()
        digest = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        logger.warning(
            "webhook_signature_check_sha256",
            secret_fingerprint=secret_fingerprint,
            payload_fingerprint=payload_fingerprint,
            received_prefix=expected[:12],
            expected_prefix=digest[:12],
            match=hmac.compare_digest(expected, digest),
        )
        return hmac.compare_digest(expected, digest)

    if signature_legacy.startswith("sha1="):
        expected = signature_legacy.split("=", 1)[1].strip().lower()
        digest = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha1,
        ).hexdigest()
        logger.warning(
            "webhook_signature_check_sha1",
            secret_fingerprint=secret_fingerprint,
            payload_fingerprint=payload_fingerprint,
            received_prefix=expected[:12],
            expected_prefix=digest[:12],
            match=hmac.compare_digest(expected, digest),
        )
        return hmac.compare_digest(expected, digest)

    logger.warning(
        "webhook_signature_header_missing_or_invalid",
        has_sha256_header=bool(signature_256),
        has_legacy_header=bool(signature_legacy),
        payload_size=len(payload),
        secret_length=len(secret),
        secret_fingerprint=secret_fingerprint,
        payload_fingerprint=payload_fingerprint,
    )
    return False


@app.on_event("startup")
async def startup():
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for webhook processing")
    app.state.redis = await create_pool(
        RedisSettings.from_dsn(settings.redis_url)
    )
    logger.info("webhook_server_started")


@app.on_event("shutdown")
async def shutdown():
    redis = getattr(app.state, "redis", None)
    if redis is not None:
        await redis.close()


@app.get("/webhook/instagram")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    """Meta webhook aboneligini dogrulama endpoint'i."""
    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="Invalid mode")
    if hub_verify_token != settings.verify_token:
        raise HTTPException(status_code=403, detail="Verification failed")
    return int(hub_challenge)


@app.post("/webhook/instagram")
async def receive_webhook(request: Request):
    """Meta'dan gelen webhook event'lerini isler."""
    body = await request.body()
    signature_256 = request.headers.get("X-Hub-Signature-256", "")
    signature_legacy = request.headers.get("X-Hub-Signature", "")

    if not verify_signature(body, signature_256, signature_legacy):
        logger.warning(
            "webhook_signature_verification_failed",
            payload_size=len(body),
            has_sha256_header=bool(signature_256),
            has_legacy_header=bool(signature_legacy),
            secret_fingerprint=_fingerprint(settings.meta_app_secret.strip()),
            payload_fingerprint=_fingerprint(body),
        )
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body)
    logger.info("webhook_received", entries=len(payload.get("entry", [])))

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            item = value.get("item")

            if item != "comment":
                continue

            comment = InstagramComment(
                comment_id=str(value.get("comment_id")),
                media_id=str(value.get("media_id")),
                from_id=str(value.get("from", {}).get("id")),
                from_username=value.get("from", {}).get("username"),
                text=value.get("comment_text", ""),
            )

            logger.info(
                "comment_triggered_for_dm",
                user=comment.from_username,
                comment_id=comment.comment_id,
                comment_text=comment.text,
            )

            await process_comment_job(comment, app.state.redis, add_delay=False)
            logger.info(
                "dm_job_processed",
                user=comment.from_username,
                comment_id=comment.comment_id,
            )

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return """
    <h1>Privacy Policy - Otomasyon cevaplama</h1>
    <p>This app automates Instagram DM responses for Altis Global. We do not store personal data.
    Data is used only to reply to user comments and messages.</p>
    <p>Contact: info@altisglobal.com.tr</p>
    """
