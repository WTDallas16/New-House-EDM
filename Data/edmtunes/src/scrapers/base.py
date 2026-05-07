from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import ArticleCard


class BaseScraper(ABC):
    source_name: str

    @abstractmethod
    def scrape_category(
        self,
        url: str,
        lookback_days: int | None = None,
        max_pages: int | None = None,
    ) -> list[ArticleCard]:
        """Return article cards discovered on a category page."""
