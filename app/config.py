from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Uygulama konfigürasyonu. .env dosyasindan okunur."""

    meta_app_secret: str
    meta_page_access_token: str
    meta_page_id: str
    instagram_account_id: str
    verify_token: str

    redis_url: str = "redis://localhost:6379/0"

    min_delay_seconds: int = 20
    max_delay_seconds: int = 50
    follower_cache_ttl_seconds: int = 300  # 5 dakika

    keywords: list[str] = ["BİLGİ", "DETAY"]
    welcome_message: str = (
        "Merhaba! 👋 Ana içeriğe ulaşmak için lütfen önce sayfamızı takip edin. "
        "Takip ettikten sonra bu gönderiye tekrar 'BİLGİ' yazabilirsiniz."
    )
    content_message: str = (
        "Teşekkürler, takibiniz için çok değerlisiniz! 🎉 "
        "İşte aradığınız bilgi: https://ornek-link.com"
    )

    @field_validator("keywords", mode="before")
    @classmethod
    def parse_keywords(cls, value):
        """.env'de 'BİLGİ,DETAY' seklinde gelse bile listeye çevirir."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("max_delay_seconds")
    @classmethod
    def validate_delays(cls, value, info):
        min_delay = info.data.get("min_delay_seconds", 0)
        if value < min_delay:
            raise ValueError("max_delay_seconds, min_delay_seconds'dan küçük olamaz")
        return value

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
