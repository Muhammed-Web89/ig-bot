from pydantic import BaseModel, Field


class InstagramComment(BaseModel):
    """Instagram yorumunun temsil edilmesi."""

    comment_id: str
    media_id: str
    from_id: str  # yorum yapan kullanicinin Instagram scoped ID'si
    from_username: str | None = None
    text: str
    created_time: int | None = None


class DMJob(BaseModel):
    """Kuyruga atilacak DM gorevi."""

    comment: InstagramComment
    attempt: int = Field(default=1, ge=1, le=5)
