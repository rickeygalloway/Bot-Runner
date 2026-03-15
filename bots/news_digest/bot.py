"""
bots/news_digest/bot.py
Fetches top headlines from RSS feeds and emails a formatted daily digest.

Sources are configured via the `topics:` block in config.yaml.
Each topic entry needs: name, url, limit.
Falls back to DEFAULT_FEEDS if no topics are configured.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import feedparser
import yaml

from core.logger import get_logger

log = get_logger("news_digest")

# ── Default RSS feeds (used if config.yaml has no topics: block) ──────────────
DEFAULT_FEEDS = [
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "limit": 5,
    },
    {
        "name": "BBC News",
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
        "limit": 5,
    },
    {
        "name": "Financial Times",
        "url": "https://www.ft.com/rss/home/uk",
        "limit": 5,
    },
]


# ── Config loading ─────────────────────────────────────────────────────────────


def _load_feeds() -> list[dict]:
    """
    Load feed list from config.yaml topics block.
    Each entry must have name, url, and limit.
    Skips entries with an empty or missing url.
    Falls back to DEFAULT_FEEDS if no valid topics found.
    """
    config_path = Path(__file__).parent / "config.yaml"
    try:
        config = yaml.safe_load(config_path.read_text())
        topics = config.get("topics") or []
        feeds = [
            {"name": t["name"], "url": t["url"], "limit": int(t.get("limit", 5))}
            for t in topics
            if t.get("url")
        ]
        if feeds:
            log.info("Loaded {} topic(s) from config.yaml", len(feeds))
            return feeds
    except Exception as exc:
        log.warning("Could not load topics from config.yaml: {}", exc)
    log.info("Using default feeds")
    return DEFAULT_FEEDS


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fetch_feed(feed_cfg: dict) -> list[dict]:
    """Fetch and parse a single RSS feed, return list of article dicts."""
    try:
        parsed = feedparser.parse(feed_cfg["url"])
        items = []
        for entry in parsed.entries[: feed_cfg["limit"]]:
            items.append(
                {
                    "title": entry.get("title", "(no title)"),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:200],
                }
            )
        log.info("Fetched {} items from {}", len(items), feed_cfg["name"])
        return items
    except Exception as exc:
        log.error("Failed to fetch feed '{}': {}", feed_cfg["name"], exc)
        return []


def _format_digest(results: dict[str, list[dict]]) -> str:
    """Format all feed results into a readable digest string."""
    lines = [
        f"📰 Daily News Digest — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 60,
    ]

    for source, articles in results.items():
        if not articles:
            continue
        lines.append(f"\n🔹 {source}")
        lines.append("-" * 40)
        for i, art in enumerate(articles, 1):
            lines.append(f"{i}. {art['title']}")
            if art["link"]:
                lines.append(f"   {art['link']}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# ── Main run() ────────────────────────────────────────────────────────────────


def run() -> str:
    """
    Entry point called by the BotRunner scheduler.
    Fetches all configured RSS feeds and returns a formatted digest string.
    The notifier in core/ will deliver it via the configured provider.
    """
    log.info("--- News Digest run starting ---")

    feeds = _load_feeds()
    all_results: dict[str, list[dict]] = {}

    for feed_cfg in feeds:
        all_results[feed_cfg["name"]] = _fetch_feed(feed_cfg)

    total = sum(len(v) for v in all_results.values())
    if total == 0:
        raise RuntimeError("All RSS feeds failed — no articles fetched.")

    digest = _format_digest(all_results)
    log.info("Digest ready — {} articles from {} sources", total, len(all_results))
    return digest
