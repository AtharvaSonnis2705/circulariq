from functools import lru_cache

from anthropic import Anthropic

from circulariq.config import get_settings


@lru_cache
def get_client() -> Anthropic:
    """Shared Claude client. Reads ANTHROPIC_API_KEY from settings; retries 429/5xx twice."""
    settings = get_settings()
    return Anthropic(api_key=settings.anthropic_api_key or None, max_retries=2)
