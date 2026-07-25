"""
Run this on your laptop, only when you're actually about to work.

It reads the latest daily digest (a public GitHub Issue, no auth needed
to read), pulls out today's pick, clones the repo, checks out a branch,
and writes a CONTEXT.md with the issue text so your coding agent has
everything it needs without burning free-tier minutes on setup.

Usage:
    python pull.py                     # uses this repo's own digest
    python pull.py owner/digest-repo   # or point at a different fork
"""

import json
import os
import re
import subprocess
import sys
import urllib.request

GITHUB_API = "https://api.github.com"
WORKDIR = os.path.expanduser("~/oss-triage")


def gh_request(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_digest(digest_repo):
    issues = gh_request(
        f"{GITHUB_API}/repos/{digest_repo}/issues"
        "?labels=daily-digest&state=all&sort=created&direction=desc&per_page=1"
    )
    if not issues:
        print("No digest found yet — has the daily-triage workflow run at least once?")
        sys.exit(1)
    return issues[0]


def extract_pick(digest_body):
    """Pull repo + issue number out of the first '### [title](url)' link."""
    match = re.search(
        r"### \[.*?\]\(https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)\)",
        digest_body,
    )
    if not match:
        print("Couldn't parse a pick out of today's digest.")
        sys.exit(1)
    return match.group(1), match.group(2)


def scaffold(repo, issue_number):
    issue = gh_request(f"{GITHUB_API}/repos/{repo}/issues/{issue_number}")
    folder = os.path.join(WORKDIR, f"{repo.replace('/', '-')}-{issue_number}")
    os.makedirs(WORKDIR, exist_ok=True)

    if not os.path.isdir(folder):
        print(f"Cloning {repo} into {folder} ...")
        subprocess.run(
            ["git", "clone", f"https://github.com/{repo}.git", folder],
            check=True,
        )
    else:
        print(f"{folder} already exists, reusing it.")

    branch = f"fix/issue-{issue_number}"
    subprocess.run(["git", "-C", folder, "checkout", "-B", branch], check=True)

    context_path = os.path.join(folder, "CONTEXT.md")
    with open(context_path, "w", encoding="utf-8") as f:
        f.write(f"# {issue['title']}\n\n")
        f.write(f"Issue: {issue['html_url']}\n\n")
        f.write("## Body\n\n")
        f.write(issue.get("body") or "(no body)")
        f.write("\n")

    print(f"\nReady: {folder}")
    print(f"Branch: {branch}")
    print(f"Context: {context_path}")
    print("\nOpen your coding agent in that folder and go.")


def main():
    digest_repo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "DIGEST_REPO", "aether-png/oss-triage-bot"
    )
    digest = latest_digest(digest_repo)
    repo, issue_number = extract_pick(digest["body"])
    scaffold(repo, issue_number)


if __name__ == "__main__":
    main()
