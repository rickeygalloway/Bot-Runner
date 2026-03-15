"""
bots/news_sentiment/bot.py
Daily AI-powered news briefing, structured by configurable topics.

Topics are a plain string list in config.yaml — Claude receives all headlines
and is instructed to cover each topic. No per-topic RSS URLs needed.
RSS feeds (the raw content source) are configured separately under feeds:.
"""

from __future__ import annotations

from pathlib import Path

import anthropic
import feedparser
import yaml

import core.config as cfg
from core.database import record_token_usage
from core.logger import get_logger

log = get_logger("news_sentiment")

MODEL = "claude-haiku-4-5-20251001"

DEFAULT_TOPICS = ["US", "World", "Finance"]

DEFAULT_FEEDS = [
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "limit": 8,
    },
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/rss.xml", "limit": 8},
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home/uk", "limit": 8},
]


def _load_config() -> tuple[list[str], list[dict]]:
    """
    Load topics (str list) and feeds (dict list) from config.yaml.
    Falls back to defaults for either if absent or invalid.
    """
    config_path = Path(__file__).parent / "config.yaml"
    topics = DEFAULT_TOPICS
    feeds = DEFAULT_FEEDS
    try:
        config = yaml.safe_load(config_path.read_text())

        raw_topics = config.get("topics") or []
        if raw_topics and all(isinstance(t, str) for t in raw_topics):
            topics = raw_topics
            log.info("Loaded {} topic(s) from config.yaml", len(topics))

        raw_feeds = config.get("feeds") or []
        valid_feeds = [
            {"name": f["name"], "url": f["url"], "limit": int(f.get("limit", 8))}
            for f in raw_feeds
            if f.get("url")
        ]
        if valid_feeds:
            feeds = valid_feeds
            log.info("Loaded {} feed(s) from config.yaml", len(feeds))

    except Exception as exc:
        log.warning("Could not load config.yaml: {}", exc)

    return topics, feeds


def _build_system_prompt(topics: list[str]) -> str:
    topics_list = "\n".join(f"- {t}" for t in topics)
    return f"""\
You are a news analyst. You will be given today's top headlines from multiple sources.

Provide a concise daily briefing structured by these topics:
{topics_list}

For each topic:
- Summarise the 1-2 most relevant stories from the headlines
- Give a one-word sentiment: Positive / Neutral / Negative

If a topic has no relevant headlines, say "No relevant stories today."

End with a **Watch**: one sentence on the single most important thing to monitor today.

Be direct and factual. This is for informational purposes only.\
"""


def _fetch_headlines(feeds: list[dict]) -> str:
    """Fetch and format headlines from all configured RSS feeds."""
    lines = []
    for feed in feeds:
        try:
            parsed = feedparser.parse(feed["url"])
            entries = parsed.entries[: feed["limit"]]
            if entries:
                lines.append(f"### {feed['name']}")
                for entry in entries:
                    lines.append(f"- {entry.get('title', '(no title)')}")
            log.info("Fetched {} headlines from {}", len(entries), feed["name"])
        except Exception as exc:
            log.error("Feed fetch failed for {}: {}", feed["name"], exc)

    if not lines:
        raise RuntimeError("All RSS feeds failed — no headlines fetched")

    return "\n".join(lines)


def _call_claude(headlines: str, system_prompt: str) -> tuple[str, str]:
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": f"Today's headlines:\n\n{headlines}"}],
    )
    usage = message.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0)
    cache_write = getattr(usage, "cache_creation_input_tokens", 0)
    log.info(
        "Token usage — input: {} (cache_read: {}) output: {}",
        usage.input_tokens,
        cache_read,
        usage.output_tokens,
    )
    record_token_usage(
        bot_name="news_sentiment",
        model=MODEL,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    body = message.content[0].text.strip()
    footer = f"\n\n---\n*Model: `{MODEL}` | Tokens: {usage.input_tokens} in"
    if cache_read:
        footer += f" ({cache_read} cached)"
    footer += f" / {usage.output_tokens} out*"
    return body, footer


def run() -> str:
    """Entry point called by the BotRunner scheduler."""
    if not cfg.ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set — add it to .env")

    log.info("News sentiment analysis starting")
    topics, feeds = _load_config()
    system_prompt = _build_system_prompt(topics)
    headlines = _fetch_headlines(feeds)
    body, footer = _call_claude(headlines, system_prompt)
    log.info("Sentiment analysis complete")

    return body + footer
