"""
Daily OSS triage: scans a curated repo list for open, unclaimed issues
that look like they need real investigation (not typo fixes or docs
stubs), and opens a single digest issue summarizing the day's finds.

Design goals:
  - No paid APIs. No GPU. Runs entirely inside GitHub Actions.
  - The repo list is curated by a human on purpose (repos.json).
  - Heuristics do the cheap filtering first; an LLM (with multi-provider
    fallback) only judges the issues that survive the heuristic pass,
    to stay well within free-tier rate limits.
  - If every LLM provider is unavailable, falls back to heuristics-only
    so the bot never goes silent for lack of an API key.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from llm_providers import ask_llm

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
DIGEST_REPO = os.environ.get("GITHUB_REPOSITORY")  # owner/repo, auto-set in Actions

MAX_ISSUES_PER_REPO = 10
MAX_COMMENTS_ALLOWED = 4          # more comments = likely already being worked
MIN_BODY_LENGTH = 200             # weak signal that it's a one-liner
MAX_DIGEST_ITEMS = 12


def gh_request(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_open_issues(repo):
    url = (
        f"{GITHUB_API}/repos/{repo}/issues"
        f"?state=open&sort=created&direction=desc&per_page={MAX_ISSUES_PER_REPO}"
    )
    try:
        issues = gh_request(url)
    except Exception as e:
        print(f"  [fetch] {repo} failed: {e}")
        return []
    # GitHub's issues endpoint also returns PRs — exclude those
    return [i for i in issues if "pull_request" not in i]


def repo_is_healthy(repo):
    """Skip repos that look dead — no point scaffolding a PR nobody will see."""
    try:
        info = gh_request(f"{GITHUB_API}/repos/{repo}")
        pushed = datetime.fromisoformat(info["pushed_at"].replace("Z", "+00:00"))
        days_since_push = (datetime.now(timezone.utc) - pushed).days
        if days_since_push > 60:
            print(f"  [health] {repo} looks inactive ({days_since_push}d since last push)")
            return False
        return True
    except Exception as e:
        print(f"  [health] {repo} check failed: {e}")
        return True  # don't block on a transient API failure


def has_maintainer_comment(repo, issue):
    """
    A maintainer already acknowledging the issue (without claiming it) is a
    strong positive signal: it's real, and it's still unassigned.
    Best-effort only — never blocks an otherwise-good issue on failure.
    """
    if issue.get("comments", 0) == 0:
        return False
    try:
        collabs = gh_request(f"{GITHUB_API}/repos/{repo}/collaborators?per_page=100")
        collab_logins = {c["login"] for c in collabs}
        comments = gh_request(issue["comments_url"])
        return any(c["user"]["login"] in collab_logins for c in comments)
    except Exception:
        return False


def passes_heuristics(issue):
    if issue.get("assignee"):
        return False
    if issue.get("comments", 0) > MAX_COMMENTS_ALLOWED:
        return False
    body = issue.get("body") or ""
    if len(body) < MIN_BODY_LENGTH:
        return False
    labels = [l["name"].lower() for l in issue.get("labels", [])]
    if any(l in ("duplicate", "wontfix", "invalid", "stale") for l in labels):
        return False
    return True


def llm_judge(issue):
    """
    Returns (worth_it: bool, reason: str, provider: str|None).
    Falls back to a heuristic-only verdict if no provider responds.
    """
    prompt = (
        "You are triaging a GitHub issue for a developer who wants "
        "high-value open source work: real bugs or substantive features, "
        "NOT typo fixes, doc tweaks, or trivial one-liners.\n\n"
        f"Title: {issue['title']}\n"
        f"Body (truncated): {(issue.get('body') or '')[:1200]}\n\n"
        "Answer with strict JSON only, no prose: "
        '{"worth_it": true or false, "reason": "one short sentence"}'
    )
    provider, response = ask_llm(prompt)
    if not response:
        # No provider available — keep it, since it already passed
        # heuristics; better to over-include than go silent.
        return True, "Passed heuristics (no LLM provider available to judge further)", None
    try:
        cleaned = response.strip().strip("`").replace("json\n", "")
        parsed = json.loads(cleaned)
        return bool(parsed.get("worth_it")), parsed.get("reason", ""), provider
    except (json.JSONDecodeError, AttributeError):
        return True, "Passed heuristics (LLM response unparseable)", provider


def _render_item(f):
    issue = f["issue"]
    lines = [f"### [{issue['title']}]({issue['html_url']})"]
    lines.append(f"- Repo: `{f['repo']}`")
    lines.append(f"- Comments: {issue.get('comments', 0)}")
    if f.get("maintainer_acknowledged"):
        lines.append("- ✅ A maintainer has already commented on this one")
    if f.get("reason"):
        lines.append(f"- Why: {f['reason']}")
    if f.get("provider"):
        lines.append(f"- _judged by: {f['provider']}_")
    return "\n".join(lines)


def build_digest(findings):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not findings:
        return None, None

    pick, rest = findings[0], findings[1:MAX_DIGEST_ITEMS]

    lines = [
        f"# Today's Pick — {today}",
        "",
        "Take this one. Don't scroll past it looking for a better one — "
        "everything below already cleared the bar.",
        "",
        _render_item(pick),
        "",
    ]
    if rest:
        lines.append("---")
        lines.append(f"<details><summary>{len(rest)} backup option(s), only if today's pick falls through</summary>")
        lines.append("")
        for f in rest:
            lines.append(_render_item(f))
            lines.append("")
        lines.append("</details>")

    title = f"Daily OSS Triage — {today}: {pick['issue']['title'][:60]}"
    return title, "\n".join(lines)


def post_digest_issue(title, body):
    if not DIGEST_REPO or not GITHUB_TOKEN:
        print("No GITHUB_REPOSITORY/GITHUB_TOKEN in env — printing digest instead:\n")
        print(title)
        print(body)
        return
    url = f"{GITHUB_API}/repos/{DIGEST_REPO}/issues"
    payload = json.dumps({"title": title, "body": body, "labels": ["daily-digest"]}).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"Posted digest: {result.get('html_url')}")
    except Exception as e:
        print(f"Failed to post digest issue: {e}")
        print(body)


def main():
    with open(os.path.join(os.path.dirname(__file__), "..", "repos.json")) as f:
        repos = json.load(f)["repos"]

    findings = []
    for repo in repos:
        print(f"Scanning {repo}...")
        if not repo_is_healthy(repo):
            continue
        issues = fetch_open_issues(repo)
        candidates = [i for i in issues if passes_heuristics(i)]
        print(f"  {len(issues)} open issues, {len(candidates)} pass heuristics")
        for issue in candidates:
            worth_it, reason, provider = llm_judge(issue)
            if worth_it:
                acknowledged = has_maintainer_comment(repo, issue)
                findings.append(
                    {
                        "repo": repo,
                        "issue": issue,
                        "reason": reason,
                        "provider": provider,
                        "maintainer_acknowledged": acknowledged,
                    }
                )

    # Maintainer-acknowledged issues surface first — strongest signal that
    # the work is real and wanted, not just unclaimed.
    findings.sort(key=lambda f: f["maintainer_acknowledged"], reverse=True)

    title, body = build_digest(findings)
    if title:
        post_digest_issue(title, body)
    else:
        print("No qualifying issues found today.")


if __name__ == "__main__":
    sys.exit(main())
