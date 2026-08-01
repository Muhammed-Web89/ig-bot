import structlog
from redis.asyncio import Redis

from app.config import settings
from app.meta_client import MetaClient

logger = structlog.get_logger()


class FollowerCache:
    """
    Takipcileri Redis uzerinde SET olarak tutar.
    Graph API'de 'X beni takip ediyor mu?' endpoint'i olmadigindan,
    kendi takipci listemizi cekip onbellekte arama yapariz.
    """

    def __init__(self, redis: Redis):
        self.redis = redis
        self.key = f"instagram:followers:{settings.instagram_account_id}"

    async def is_following(self, user_id: str) -> bool:
        """Kullanici ID'si onbellekte var mi?"""
        return await self.redis.sismember(self.key, user_id)

    async def refresh(self) -> None:
        """
        Takipcileri Graph API'den cekip Redis'e yazar.
        DIKKAT: Milyonluk hesaplarda bu uzun surer ve rate-limit yiyebilir.
        O durumda 'iki adimli dogrulama' yaklasimi daha uygundur.
        """
        client = MetaClient()
        try:
            await self.redis.delete(self.key)
            cursor = None
            page_count = 0
            total = 0

            while True:
                data = await client.get_followers_page(after_cursor=cursor)
                followers = data.get("data", [])
                if followers:
                    ids = [f["id"] for f in followers]
                    await self.redis.sadd(self.key, *ids)
                    total += len(ids)

                paging = data.get("paging", {})
                cursors = paging.get("cursors", {})
                cursor = cursors.get("after")
                page_count += 1

                logger.info(
                    "followers_page_fetched",
                    page=page_count,
                    page_size=len(followers),
                    total=total,
                )

                if not cursor:
                    break

            await self.redis.expire(
                self.key, settings.follower_cache_ttl_seconds
            )
            logger.info("follower_cache_refreshed", total=total)
        finally:
            await client.close()
