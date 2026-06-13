"""Лёгкие агенты CLI: время и веб-поиск. Календарь (macOS-only) опущен."""
from datetime import datetime

try:
    from ddgs import DDGS  # новое имя пакета duckduckgo_search
except ImportError:  # pragma: no cover
    from duckduckgo_search import DDGS


class TimeAgent:
    def run(self, query: str = "now") -> str:
        now = datetime.now()
        return f"Сейчас {now.strftime('%H:%M')}, {now.strftime('%A, %d %B %Y')}."


class SearchAgent:
    def fetch(self, query: str, max_results: int = 5) -> list[dict]:
        """Структурированные результаты DuckDuckGo: title/body/href."""
        with DDGS() as ddgs:
            raw = ddgs.text(query, region="ru-ru", safesearch="off", max_results=max_results)
            return [
                {"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                for r in (raw or [])
            ]
