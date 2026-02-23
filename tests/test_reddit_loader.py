"""Reddit loader unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.research.scrape.reddit_loader import (
    RedditLoader,
    _classify_reddit_url,
    _flatten_comments,
    _format_post_markdown,
    _format_subreddit_markdown,
    _make_json_url,
)


# --- URL classification tests (sync) ---


def test_classify_post_url():
    url = "https://www.reddit.com/r/Python/comments/abc123/some_title/"
    assert _classify_reddit_url(url) == "post"


def test_classify_post_url_no_trailing_slash():
    url = "https://reddit.com/r/learnpython/comments/xyz789/my_post"
    assert _classify_reddit_url(url) == "post"


def test_classify_subreddit_url():
    url = "https://www.reddit.com/r/Python/"
    assert _classify_reddit_url(url) == "subreddit"


def test_classify_subreddit_url_no_trailing_slash():
    url = "https://www.reddit.com/r/Python"
    assert _classify_reddit_url(url) == "subreddit"


def test_classify_user_url():
    url = "https://www.reddit.com/u/spez"
    assert _classify_reddit_url(url) == "user"


def test_classify_user_url_long_form():
    url = "https://www.reddit.com/user/some_user/"
    assert _classify_reddit_url(url) == "user"


def test_classify_unknown_url():
    url = "https://www.reddit.com/"
    assert _classify_reddit_url(url) == "unknown"


def test_classify_unknown_url_weird_path():
    url = "https://www.reddit.com/gallery/abc123"
    assert _classify_reddit_url(url) == "unknown"


# --- JSON URL conversion tests (sync) ---


def test_make_json_url_basic():
    url = "https://www.reddit.com/r/Python/comments/abc123/some_title/"
    result = _make_json_url(url)
    assert result.endswith("/r/Python/comments/abc123/some_title.json")


def test_make_json_url_already_json():
    url = "https://www.reddit.com/r/Python/comments/abc123.json"
    result = _make_json_url(url)
    assert result.endswith(".json")
    assert not result.endswith(".json.json")


def test_make_json_url_preserves_query():
    url = "https://www.reddit.com/r/Python?sort=hot"
    result = _make_json_url(url)
    assert "sort=hot" in result
    assert ".json" in result


# --- Comment flattening tests (sync) ---


def _make_comment(
    author: str = "testuser",
    body: str = "test comment",
    score: int = 10,
    replies: dict | str = "",
) -> dict:
    """Build a minimal Reddit comment structure."""
    return {
        "kind": "t1",
        "data": {
            "author": author,
            "body": body,
            "score": score,
            "replies": replies,
        },
    }


def _make_more_stub() -> dict:
    return {"kind": "more", "data": {"children": ["abc", "def"]}}


def test_flatten_basic_comments():
    children = [
        _make_comment(author="alice", body="great post", score=20),
        _make_comment(author="bob", body="thanks", score=15),
    ]
    result = _flatten_comments(children, max_depth=3, max_comments=10, min_score=1)
    assert len(result) == 2
    assert result[0]["author"] == "alice"
    assert result[1]["author"] == "bob"
    assert all(c["depth"] == 0 for c in result)


def test_flatten_respects_max_comments():
    children = [_make_comment(body=f"comment {i}", score=10) for i in range(20)]
    result = _flatten_comments(children, max_depth=3, max_comments=5, min_score=1)
    assert len(result) == 5


def test_flatten_filters_by_score():
    children = [
        _make_comment(body="high score", score=50),
        _make_comment(body="low score", score=0),
    ]
    result = _flatten_comments(children, max_depth=3, max_comments=10, min_score=5)
    assert len(result) == 1
    assert result[0]["body"] == "high score"


def test_flatten_skips_deleted():
    children = [
        _make_comment(author="[deleted]", body="[deleted]", score=10),
        _make_comment(author="real_user", body="real comment", score=10),
    ]
    result = _flatten_comments(children, max_depth=3, max_comments=10, min_score=1)
    assert len(result) == 1
    assert result[0]["author"] == "real_user"


def test_flatten_skips_removed():
    children = [
        _make_comment(body="[removed]", score=10),
        _make_comment(body="visible comment", score=10),
    ]
    result = _flatten_comments(children, max_depth=3, max_comments=10, min_score=1)
    assert len(result) == 1
    assert result[0]["body"] == "visible comment"


def test_flatten_skips_more_stubs():
    children = [
        _make_comment(body="real comment", score=10),
        _make_more_stub(),
    ]
    result = _flatten_comments(children, max_depth=3, max_comments=10, min_score=1)
    assert len(result) == 1


def test_flatten_nested_replies():
    reply = _make_comment(author="replier", body="nice", score=10)
    parent = _make_comment(
        author="parent",
        body="top comment",
        score=20,
        replies={
            "data": {"children": [reply]},
        },
    )
    result = _flatten_comments([parent], max_depth=3, max_comments=10, min_score=1)
    assert len(result) == 2
    assert result[0]["depth"] == 0
    assert result[1]["depth"] == 1
    assert result[1]["author"] == "replier"


def test_flatten_respects_depth_limit():
    deep_reply = _make_comment(author="deep", body="deep comment", score=10)
    mid_reply = _make_comment(
        author="mid",
        body="mid comment",
        score=10,
        replies={"data": {"children": [deep_reply]}},
    )
    top = _make_comment(
        author="top",
        body="top comment",
        score=10,
        replies={"data": {"children": [mid_reply]}},
    )
    # max_depth=2 means depths 0 and 1 only
    result = _flatten_comments([top], max_depth=2, max_comments=10, min_score=1)
    assert len(result) == 2
    assert result[0]["author"] == "top"
    assert result[1]["author"] == "mid"


# --- Formatting tests (sync) ---


def test_format_post_markdown():
    post_data = {
        "title": "Test Post",
        "author": "testuser",
        "subreddit": "Python",
        "score": 42,
        "selftext": "This is the post body.",
    }
    comments = [
        {"author": "commenter", "body": "Great post!", "score": 10, "depth": 0},
    ]
    result = _format_post_markdown(post_data, comments)
    assert "## Test Post" in result
    assert "u/testuser" in result
    assert "r/Python" in result
    assert "42 points" in result
    assert "This is the post body." in result
    assert "### Top Comments" in result
    assert "u/commenter" in result


def test_format_post_markdown_no_selftext():
    post_data = {
        "title": "Link Post",
        "author": "poster",
        "subreddit": "news",
        "score": 100,
        "selftext": "",
    }
    result = _format_post_markdown(post_data, [])
    assert "## Link Post" in result
    assert "### Top Comments" not in result


def test_format_post_markdown_crosspost():
    post_data = {
        "title": "Crosspost",
        "author": "poster",
        "subreddit": "test",
        "score": 5,
        "selftext": "",
        "crosspost_parent_list": [{"selftext": "Original content here"}],
    }
    result = _format_post_markdown(post_data, [])
    assert "Original content here" in result


def test_format_subreddit_markdown():
    listing = [
        {
            "kind": "t3",
            "data": {
                "title": "First Post",
                "author": "user1",
                "score": 100,
                "num_comments": 50,
                "selftext": "Some preview text",
            },
        },
        {
            "kind": "t3",
            "data": {
                "title": "Second Post",
                "author": "user2",
                "score": 50,
                "num_comments": 10,
                "selftext": "",
            },
        },
    ]
    result = _format_subreddit_markdown(listing)
    assert "**First Post**" in result
    assert "**Second Post**" in result
    assert "Some preview text" in result


# --- Full loader tests (async, mocked httpx) ---


def _make_post_json(
    title: str = "Test Post",
    selftext: str = "A" * 200,
    author: str = "testuser",
    score: int = 42,
    subreddit: str = "Python",
    comments: list | None = None,
) -> list:
    """Build a minimal Reddit post JSON response."""
    if comments is None:
        comments = [
            {
                "kind": "t1",
                "data": {
                    "author": "commenter",
                    "body": "Great post!",
                    "score": 10,
                    "replies": "",
                },
            },
        ]
    return [
        {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": title,
                            "selftext": selftext,
                            "author": author,
                            "score": score,
                            "subreddit": subreddit,
                            "num_comments": len(comments),
                        },
                    }
                ],
            },
        },
        {
            "data": {
                "children": comments,
            },
        },
    ]


def _make_subreddit_json(posts: int = 5) -> dict:
    """Build a minimal subreddit listing JSON response."""
    children = [
        {
            "kind": "t3",
            "data": {
                "title": f"Post {i}",
                "author": f"user{i}",
                "score": 100 - i * 10,
                "num_comments": 50 - i * 5,
                "selftext": f"Content of post {i} " * 20,
                "subreddit": "Python",
            },
        }
        for i in range(posts)
    ]
    return {"data": {"children": children}}


@pytest.mark.asyncio
async def test_loader_successful_post():
    loader = RedditLoader(request_delay=0)
    post_json = _make_post_json()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = post_json
    mock_response.raise_for_status = MagicMock()

    with patch("src.research.scrape.reddit_loader.httpx.AsyncClient") as mock_client:
        ctx = AsyncMock()
        ctx.get.return_value = mock_response
        mock_client.return_value.__aenter__ = AsyncMock(return_value=ctx)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await loader.load(
            "https://www.reddit.com/r/Python/comments/abc123/test/"
        )

    assert result is not None
    assert result.url == "https://www.reddit.com/r/Python/comments/abc123/test/"
    assert "Test Post" in result.content
    assert result.title == "Test Post"


@pytest.mark.asyncio
async def test_loader_http_error_returns_none():
    loader = RedditLoader(request_delay=0)

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429 Too Many Requests",
        request=MagicMock(),
        response=MagicMock(status_code=429),
    )

    with patch("src.research.scrape.reddit_loader.httpx.AsyncClient") as mock_client:
        ctx = AsyncMock()
        ctx.get.return_value = mock_response
        mock_client.return_value.__aenter__ = AsyncMock(return_value=ctx)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await loader.load(
            "https://www.reddit.com/r/Python/comments/abc123/test/"
        )

    assert result is None


@pytest.mark.asyncio
async def test_loader_short_content_returns_none():
    """Posts with minimal text content (< 100 chars) should return None."""
    loader = RedditLoader(request_delay=0)
    # Very short selftext, no comments → content under 100 chars
    post_json = _make_post_json(selftext="Short", comments=[])

    mock_response = MagicMock()
    mock_response.json.return_value = post_json
    mock_response.raise_for_status = MagicMock()

    with patch("src.research.scrape.reddit_loader.httpx.AsyncClient") as mock_client:
        ctx = AsyncMock()
        ctx.get.return_value = mock_response
        mock_client.return_value.__aenter__ = AsyncMock(return_value=ctx)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await loader.load(
            "https://www.reddit.com/r/Python/comments/abc123/test/"
        )

    assert result is None


@pytest.mark.asyncio
async def test_loader_subreddit_listing():
    loader = RedditLoader(request_delay=0)
    listing_json = _make_subreddit_json(posts=5)

    mock_response = MagicMock()
    mock_response.json.return_value = listing_json
    mock_response.raise_for_status = MagicMock()

    with patch("src.research.scrape.reddit_loader.httpx.AsyncClient") as mock_client:
        ctx = AsyncMock()
        ctx.get.return_value = mock_response
        mock_client.return_value.__aenter__ = AsyncMock(return_value=ctx)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await loader.load("https://www.reddit.com/r/Python/")

    assert result is not None
    assert "Post 0" in result.content
    assert "Post 4" in result.content


@pytest.mark.asyncio
async def test_loader_unknown_url_returns_none():
    loader = RedditLoader(request_delay=0)
    result = await loader.load("https://www.reddit.com/")
    assert result is None


@pytest.mark.asyncio
async def test_loader_truncates_long_content():
    loader = RedditLoader(request_delay=0, max_content_length=500)
    post_json = _make_post_json(selftext="A" * 1000)

    mock_response = MagicMock()
    mock_response.json.return_value = post_json
    mock_response.raise_for_status = MagicMock()

    with patch("src.research.scrape.reddit_loader.httpx.AsyncClient") as mock_client:
        ctx = AsyncMock()
        ctx.get.return_value = mock_response
        mock_client.return_value.__aenter__ = AsyncMock(return_value=ctx)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await loader.load(
            "https://www.reddit.com/r/Python/comments/abc123/test/"
        )

    assert result is not None
    assert result.content.endswith("[truncated]")


# --- Registry integration tests (sync) ---


def test_registry_returns_reddit_loader_for_reddit_urls():
    """build_default_registry should use RedditLoader for reddit.com."""
    from src.research.scrape import RedditLoader, build_default_registry

    settings = MagicMock()
    settings.firecrawl_api_key = "test"
    settings.firecrawl_api_url = ""
    settings.reddit_max_comments = 10
    settings.reddit_max_comment_depth = 3
    settings.reddit_min_comment_score = 2
    settings.reddit_max_content_length = 15000
    settings.reddit_request_delay = 0.5
    settings.reddit_user_agent = "test-agent"

    registry = build_default_registry(settings)
    loader = registry.get_loader("https://www.reddit.com/r/Python/comments/abc/test")
    assert isinstance(loader, RedditLoader)


def test_registry_returns_reddit_loader_for_redd_it():
    """build_default_registry should use RedditLoader for redd.it short URLs."""
    from src.research.scrape import RedditLoader, build_default_registry

    settings = MagicMock()
    settings.firecrawl_api_key = "test"
    settings.firecrawl_api_url = ""
    settings.reddit_max_comments = 10
    settings.reddit_max_comment_depth = 3
    settings.reddit_min_comment_score = 2
    settings.reddit_max_content_length = 15000
    settings.reddit_request_delay = 0.5
    settings.reddit_user_agent = "test-agent"

    registry = build_default_registry(settings)
    loader = registry.get_loader("https://redd.it/abc123")
    assert isinstance(loader, RedditLoader)
