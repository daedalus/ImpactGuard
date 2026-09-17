"""Post or update a sticky pull-request comment carrying an ImpactGuard
report, for use from CI (see ``action.yml``).

Ported concept (independent implementation, stdlib-only) from
officefloor/ImpactGate's ``ghapi.py``: a hidden HTML marker identifies "our"
comment on the PR, so re-running on a new push edits that one comment in
place instead of piling up a new comment per push.

GitHub only for now; GitLab MR notes are a natural follow-up (ImpactGate's
``glapi.py`` is the reference for the same pattern against the GitLab API)
but are out of scope here to keep this module's surface small and testable.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from ._logging import get_logger

_log = get_logger(__name__)

MARKER = "<!-- impactguard -->"
API_ROOT = "https://api.github.com"


@dataclass
class CommentTarget:
    repo_slug: str  # "owner/name"
    pr_number: int
    token: str


class GitHubAPIError(RuntimeError):
    pass


def _request(method: str, url: str, token: str, body: dict | None = None) -> object:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GitHubAPIError(f"{method} {url} -> {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubAPIError(f"{method} {url} -> {exc.reason}") from exc


def list_issue_comments(target: CommentTarget) -> list:
    url = f"{API_ROOT}/repos/{target.repo_slug}/issues/{target.pr_number}/comments"
    result = _request("GET", url, target.token)
    return result if isinstance(result, list) else []


def find_existing(comments: list, marker: str = MARKER):
    """Return the id of the first comment whose body carries *marker*, or
    None if this is the first run on this PR."""
    for c in comments:
        if marker in (c.get("body") or ""):
            return c.get("id")
    return None


def upsert_comment(target: CommentTarget, body: str, marker: str = MARKER) -> str:
    """Create the sticky comment if none exists yet, otherwise edit the
    existing one in place. Returns the comment's html_url."""
    tagged = f"{marker}\n{body}"
    existing_id = find_existing(list_issue_comments(target), marker)

    if existing_id is not None:
        url = f"{API_ROOT}/repos/{target.repo_slug}/issues/comments/{existing_id}"
        result = _request("PATCH", url, target.token, {"body": tagged})
    else:
        url = f"{API_ROOT}/repos/{target.repo_slug}/issues/{target.pr_number}/comments"
        result = _request("POST", url, target.token, {"body": tagged})

    return result.get("html_url", "") if isinstance(result, dict) else ""
