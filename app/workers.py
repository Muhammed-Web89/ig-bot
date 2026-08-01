import asyncio
import random
import structlog
from redis.asyncio import Redis
from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings
from app.followers import FollowerCache
from app.meta_client import MetaClient, MetaAPIError, MetaRateLimitError
from app.models import DMJob

logger = structlog.get_logger()


def require_redis_settings() -> RedisSettings:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for worker startup")
    return RedisSettings.from_dsn(settings.redis_url)


async def send_dm_task(ctx, job_data: dict):
    """
    Kuyruktan cekilen gorev:
    1. Rastgele gecikme uygula (anti-spam)
    2. Kullanicinin takip durumunu kontrol et (cache-first)
    3. Uygun mesaji Private Reply ile gonder
    4. Hata durumunda retry schedule'la
    """
    job = DMJob(**job_data)
    comment = job.comment
    redis: Redis = ctx["redis"]

    # Anti-spam: her DM gonderiminden once rastgele bekleme
    delay = random.randint(
        settings.min_delay_seconds, settings.max_delay_seconds
    )
    logger.info(
        "dm_delay_started",
        user=comment.from_username,
        delay=delay,
        comment_id=comment.comment_id,
        attempt=job.attempt,
    )
    await asyncio.sleep(delay)

    follower_cache = FollowerCache(redis)
    client = MetaClient()

    try:
        # 1. Once cache'e bak
        is_following = await follower_cache.is_following(comment.from_id)

        # Cache miss olursa takipci listesini guncelle (kucuk hesaplarda)
        if not is_following:
            logger.info(
                "cache_miss_refreshing_followers",
                user=comment.from_username,
            )
            await follower_cache.refresh()
            is_following = await follower_cache.is_following(comment.from_id)

        # 2. Mesaji belirle
        if is_following:
            message = settings.content_message
            logger.info("user_is_follower", user=comment.from_username)
        else:
            message = settings.welcome_message
            logger.info("user_is_not_follower", user=comment.from_username)

        # 3. Private Reply ile DM gonder
        result = await client.send_private_reply(comment.comment_id, message)
        logger.info(
            "dm_sent",
            user=comment.from_username,
            comment_id=comment.comment_id,
            message_type="content" if is_following else "welcome",
        )
        return result

    except MetaRateLimitError as exc:
        logger.error(
            "rate_limit_hit",
            user=comment.from_username,
            error=str(exc),
        )
        if job.attempt < 5:
            await redis.enqueue_job(
                "send_dm_task",
                job.model_copy(update={"attempt": job.attempt + 1}).model_dump(),
                defer_by_seconds=60 * job.attempt,
            )
    except MetaAPIError as exc:
        logger.error(
            "meta_api_error",
            user=comment.from_username,
            error=str(exc),
        )
    except Exception:
        logger.exception(
            "unexpected_error",
            user=comment.from_username,
            comment_id=comment.comment_id,
        )
    finally:
        await client.close()


async def startup(ctx):
    ctx["redis"] = await create_pool(require_redis_settings())


async def shutdown(ctx):
    await ctx["redis"].close()


class WorkerSettings:
    redis_settings = require_redis_settings()
    functions = [send_dm_task]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 5  # Ayni anda calisan worker gorevi sayisi
    job_timeout = 300
