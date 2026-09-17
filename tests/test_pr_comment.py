"""Tests for ImpactGuard's PR comment upsert helper (pr_comment.py)."""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from impactguard.pr_comment import (
    CommentTarget,
    GitHubAPIError,
    MARKER,
    find_existing,
    upsert_comment,
)


def _target():
    return CommentTarget(repo_slug="daedalus/ImpactGuard", pr_number=42, token="tok")


def test_find_existing_none_when_no_marker():
    comments = [{"id": 1, "body": "hi"}, {"id": 2, "body": "unrelated"}]
    assert find_existing(comments) is None


def test_find_existing_finds_marked_comment():
    comments = [{"id": 1, "body": "hi"}, {"id": 2, "body": f"{MARKER}\nreport"}]
    assert find_existing(comments) == 2


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_upsert_creates_when_no_existing_comment():
    list_resp = _FakeResponse([])
    create_resp = _FakeResponse({"html_url": "https://github.com/x/y/pull/42#comment"})

    with patch("impactguard.pr_comment.urllib.request.urlopen", side_effect=[list_resp, create_resp]) as m:
        url = upsert_comment(_target(), "the report body")

    assert url == "https://github.com/x/y/pull/42#comment"
    # Second call should be a POST to the issue comments collection endpoint.
    second_req = m.call_args_list[1][0][0]
    assert second_req.get_method() == "POST"
    assert second_req.full_url.endswith("/repos/daedalus/ImpactGuard/issues/42/comments")
    sent_body = json.loads(second_req.data.decode("utf-8"))
    assert sent_body["body"].startswith(MARKER)
    assert "the report body" in sent_body["body"]


def test_upsert_edits_existing_comment_in_place():
    list_resp = _FakeResponse([{"id": 7, "body": f"{MARKER}\nold report"}])
    patch_resp = _FakeResponse({"html_url": "https://github.com/x/y/pull/42#comment-7"})

    with patch("impactguard.pr_comment.urllib.request.urlopen", side_effect=[list_resp, patch_resp]) as m:
        url = upsert_comment(_target(), "new report body")

    assert url == "https://github.com/x/y/pull/42#comment-7"
    second_req = m.call_args_list[1][0][0]
    assert second_req.get_method() == "PATCH"
    assert second_req.full_url.endswith("/repos/daedalus/ImpactGuard/issues/comments/7")


def test_upsert_raises_on_http_error():
    import urllib.error

    err = urllib.error.HTTPError(
        url="x", code=403, msg="Forbidden", hdrs=None, fp=io.BytesIO(b"nope")
    )
    with patch("impactguard.pr_comment.urllib.request.urlopen", side_effect=err):
        try:
            upsert_comment(_target(), "body")
            assert False, "expected GitHubAPIError"
        except GitHubAPIError as exc:
            assert "403" in str(exc)
