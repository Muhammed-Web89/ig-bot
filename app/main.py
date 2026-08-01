import hmac
import hashlib
import json
import structlog
from fastapi import FastAPI, Request, HTTPException, Query
from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings
from app.models import InstagramComment, DMJob

logger = structlog.get_logger()
app = FastAPI(title="Instagram Auto DM")


def verify_signature(payload: bytes, signature: str) -> bool:
    """X-Hub-Signature-256 basligini dogrular."""
    if not signature.startswith("sha256="):
        return False
    expected = signature.split("=")[1]
    digest = hmac.new(
        settings.meta_app_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, digest)


@app.on_event("startup")
async def startup():
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for webhook queue processing")
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
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body)
    logger.info("webhook_received", entries=len(payload.get("entry", [])))

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            item = value.get("item")

            if item != "comment":
                continue

            comment_text = value.get("comment_text", "").upper()
            if not any(kw.upper() in comment_text for kw in settings.keywords):
                continue

            comment = InstagramComment(
                comment_id=str(value.get("comment_id")),
                media_id=str(value.get("media_id")),
                from_id=str(value.get("from", {}).get("id")),
                from_username=value.get("from", {}).get("username"),
                text=value.get("comment_text", ""),
            )

            await app.state.redis.enqueue_job(
                "send_dm_task",
                DMJob(comment=comment).model_dump(),
            )
            logger.info(
                "dm_job_enqueued",
                user=comment.from_username,
                comment_id=comment.comment_id,
            )

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
