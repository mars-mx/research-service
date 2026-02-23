"""Reddit page loader — fetches Reddit JSON API and formats as markdown."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from .models import ScrapedPage

logger = logging.getLogger(__name__)

# URL path patterns
_POST_RE = re.compile(r"/r/\w+/comments/\w+")
_SUBREDDIT_RE = re.compile(r"/r/\w+/?$")
_USER_RE = re.compile(r"/u(ser)?/\w+")


def _classify_reddit_url(url: str) -> str:
    """Classify a Reddit URL as 'post', 'subreddit', 'user', or 'unknown'."""
    from urllib.parse import urlparse

    path = urlparse(url).path.rstrip("/")

    if _POST_RE.search(path):
        return "post"
    if _SUBREDDIT_RE.search(path):
        return "subreddit"
    if _USER_RE.search(path):
        return "user"
    return "unknown"


def _make_json_url(url: str) -> str:
    """Convert a Reddit URL to its JSON API equivalent."""
    # Strip trailing slash, query params stay
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path.endswith(".json"):
        path += ".json"
    return urlunparse(parsed._replace(path=path))


def _flatten_comments(
    children: list[dict[str, Any]],
    *,
    max_depth: int = 3,
    max_comments: int = 10,
    min_score: int = 2,
    _current_depth: int = 0,
) -> list[dict[str, Any]]:
    """Recursively flatten Reddit's nested comment tree.

    Returns a flat list of ``{author, body, score, depth}`` dicts,
    filtered by score and depth, skipping deleted/removed comments.
    """
    results: list[dict[str, Any]] = []

    if _current_depth >= max_depth:
        return results

    for child in children:
        if len(results) >= max_comments:
            break

        # Skip "more comments" stubs
        if child.get("kind") != "t1":
            continue

        data = child.get("data", {})
        body = data.get("body", "")
        author = data.get("author", "")
        score = data.get("score", 0)

        # Skip deleted/removed
        if body in ("[deleted]", "[removed]", ""):
            continue
        if author in ("[deleted]", "[removed]"):
            continue

        # Score filter (only apply to non-top-level to keep some top comments)
        if _current_depth > 0 and score < min_score:
            continue
        if _current_depth == 0 and score < min_score:
            continue

        results.append({
            "author": author,
            "body": body,
            "score": score,
            "depth": _current_depth,
        })

        # Recurse into replies
        replies = data.get("replies")
        if isinstance(replies, dict):
            reply_children = (
                replies.get("data", {}).get("children", [])
            )
            remaining = max_comments - len(results)
            if remaining > 0 and reply_children:
                nested = _flatten_comments(
                    reply_children,
                    max_depth=max_depth,
                    max_comments=remaining,
                    min_score=min_score,
                    _current_depth=_current_depth + 1,
                )
                results.extend(nested)

    return results[:max_comments]


def _format_post_markdown(
    post_data: dict[str, Any],
    comments: list[dict[str, Any]],
) -> str:
    """Format a Reddit post and its comments as structured markdown."""
    title = post_data.get("title", "Untitled")
    author = post_data.get("author", "unknown")
    subreddit = post_data.get("subreddit", "unknown")
    score = post_data.get("score", 0)
    selftext = post_data.get("selftext", "")

    # Check for crossposted content
    if not selftext:
        crosspost_list = post_data.get("crosspost_parent_list", [])
        if crosspost_list:
            selftext = crosspost_list[0].get("selftext", "")

    lines = [
        f"## {title}",
        f"**Posted by** u/{author} in r/{subreddit} | {score} points",
        "",
    ]

    if selftext:
        lines.append(selftext)
        lines.append("")

    if comments:
        lines.append("---")
        lines.append("### Top Comments")
        lines.append("")

        for comment in comments:
            indent = "> " * comment["depth"]
            lines.append(
                f"{indent}**u/{comment['author']}** ({comment['score']} points):"
            )
            # Indent comment body lines
            for body_line in comment["body"].splitlines():
                lines.append(f"{indent}{body_line}")
            lines.append("")

    return "\n".join(lines)


def _format_subreddit_markdown(
    listing_data: list[dict[str, Any]],
) -> str:
    """Format a subreddit listing as a bulleted list of post summaries."""
    lines = []
    for child in listing_data:
        if child.get("kind") != "t3":
            continue
        data = child.get("data", {})
        title = data.get("title", "Untitled")
        score = data.get("score", 0)
        author = data.get("author", "unknown")
        num_comments = data.get("num_comments", 0)
        selftext = data.get("selftext", "")

        preview = selftext[:200].replace("\n", " ") if selftext else ""
        lines.append(
            f"- **{title}** (u/{author}, {score} pts, "
            f"{num_comments} comments)"
        )
        if preview:
            lines.append(f"  {preview}")
    return "\n".join(lines)


class RedditLoader:
    """Loads Reddit pages via the Reddit JSON API (append .json to URL)."""

    def __init__(
        self,
        *,
        max_comments: int = 10,
        max_comment_depth: int = 3,
        min_comment_score: int = 2,
        max_content_length: int = 15000,
        request_delay: float = 0.5,
        user_agent: str = "research-service/0.1.0",
    ) -> None:
        self._max_comments = max_comments
        self._max_comment_depth = max_comment_depth
        self._min_comment_score = min_comment_score
        self._max_content_length = max_content_length
        self._request_delay = request_delay
        self._user_agent = user_agent

    async def load(self, url: str) -> ScrapedPage | None:
        """Fetch a Reddit URL via JSON API and return structured markdown."""
        url_type = _classify_reddit_url(url)
        if url_type == "unknown":
            logger.warning("unrecognised reddit URL type", extra={"url": url})
            return None

        logger.debug("reddit loading", extra={"url": url, "url_type": url_type})
        json_url = _make_json_url(url)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": self._user_agent},
            ) as client:
                if self._request_delay > 0:
                    await asyncio.sleep(self._request_delay)
                resp = await client.get(json_url, timeout=15.0)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.warning("reddit fetch failed", extra={"url": url}, exc_info=True)
            return None

        try:
            if url_type == "post":
                content = self._handle_post(data)
            elif url_type == "subreddit":
                content = self._handle_listing(data)
            else:
                # user pages have the same listing structure
                content = self._handle_listing(data)
        except Exception:
            logger.warning("reddit parse failed", extra={"url": url}, exc_info=True)
            return None

        if not content or len(content) < 100:
            logger.debug(
                "reddit content too short, discarding",
                extra={"url": url, "length": len(content) if content else 0},
            )
            return None

        # Truncate if over limit
        if len(content) > self._max_content_length:
            logger.debug(
                "reddit content truncated",
                extra={"url": url, "original_length": len(content), "max_length": self._max_content_length},
            )
            content = content[: self._max_content_length] + "\n\n[truncated]"

        title = self._extract_title(data, url_type)
        logger.debug("reddit loaded", extra={"url": url, "url_type": url_type, "content_length": len(content), "title": title[:80]})

        return ScrapedPage(url=url, title=title, content=content)

    def _handle_post(self, data: Any) -> str:
        """Parse post JSON (list of two listings) into markdown."""
        post_data = data[0]["data"]["children"][0]["data"]
        comment_children = data[1]["data"]["children"]

        comments = _flatten_comments(
            comment_children,
            max_depth=self._max_comment_depth,
            max_comments=self._max_comments,
            min_score=self._min_comment_score,
        )
        return _format_post_markdown(post_data, comments)

    def _handle_listing(self, data: Any) -> str:
        """Parse subreddit/user listing JSON into markdown."""
        # Listing responses are a single dict with data.children
        children = data["data"]["children"]
        return _format_subreddit_markdown(children)

    def _extract_title(self, data: Any, url_type: str) -> str:
        """Extract a title from the JSON response."""
        try:
            if url_type == "post":
                return data[0]["data"]["children"][0]["data"].get(
                    "title", ""
                )
            # For listings, use the subreddit display name
            children = data["data"]["children"]
            if children:
                return "r/" + children[0]["data"].get("subreddit", "")
        except (KeyError, IndexError, TypeError):
            pass
        return ""
