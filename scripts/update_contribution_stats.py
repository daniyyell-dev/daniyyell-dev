#!/usr/bin/env python3
"""Generate a public, all-time PR/issue card from GitHub's GraphQL API.

Requires the GitHub CLI and an authenticated GH_TOKEN (GITHUB_TOKEN in Actions).
External repositories means distinct non-owned repositories receiving authored PRs.
No private repository names or activity are requested or written.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERY = """
query($prQuery: String!, $issueQuery: String!, $cursor: String) {
  prs: search(query: $prQuery, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { state merged repository { nameWithOwner owner { login } } } }
  }
  issues: search(query: $issueQuery, type: ISSUE, first: 1) { issueCount }
}
"""


def fetch_stats(username: str) -> dict[str, int]:
    """Fetch every public authored PR, failing rather than truncating at 1,000."""
    cursor = None
    pulls = []
    while True:
        command = [
            "gh", "api", "graphql", "-f", f"query={QUERY}",
            "-f", f"prQuery=author:{username} is:pr is:public",
            "-f", f"issueQuery=author:{username} is:issue is:public",
        ]
        if cursor:
            command.extend(["-f", f"cursor={cursor}"])
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        response = json.loads(result.stdout)
        if response.get("errors"):
            raise RuntimeError("GitHub returned GraphQL errors; keeping the previous card")
        data = response["data"]
        page = data["prs"]
        if page["issueCount"] > 1000:
            raise RuntimeError("PR search exceeds 1,000 results; split the query before updating")
        pulls.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    if len(pulls) != page["issueCount"] or any(not p for p in pulls):
        raise RuntimeError("Incomplete PR results; keeping the previous card")
    return {
        "pull_requests": len(pulls),
        "merged_pull_requests": sum(p["merged"] for p in pulls),
        "open_pull_requests": sum(p["state"] == "OPEN" for p in pulls),
        "closed_unmerged_pull_requests": sum(p["state"] == "CLOSED" for p in pulls),
        "issues_opened": data["issues"]["issueCount"],
        "external_repositories": len({
            p["repository"]["nameWithOwner"] for p in pulls
            if p["repository"]["owner"]["login"].casefold() != username.casefold()
        }),
    }


def render_card(stats: dict[str, int], updated_at: str) -> str:
    rows = [
        ("Pull requests submitted", stats["pull_requests"]),
        ("Merged pull requests", stats["merged_pull_requests"]),
        ("Open pull requests", stats["open_pull_requests"]),
        ("Issues opened", stats["issues_opened"]),
        ("External repos with PRs", stats["external_repositories"]),
    ]
    description = "; ".join(f"{label}: {value}" for label, value in rows)
    description += f". Public activity, all time. Updated {updated_at}."
    elements = []
    for index, (label, value) in enumerate(rows):
        y = 91 + index * 34
        elements.append(
            f'<text x="25" y="{y}" class="label">{escape(label)}</text>'
            f'<text x="415" y="{y}" class="value" text-anchor="end">{value:,}</text>'
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="440" height="316" viewBox="0 0 440 316" role="img" aria-labelledby="title desc">
  <title id="title">Open-source contributions</title>
  <desc id="desc">{escape(description)}</desc>
  <style>
    text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    .heading {{ fill: #FF2020; font-size: 20px; font-weight: 650; }}
    .label {{ fill: #E5E7EB; font-size: 15px; }}
    .value {{ fill: #E5E7EB; font-size: 18px; font-weight: 700; }}
    .note {{ fill: #9CA3AF; font-size: 11px; }}
  </style>
  <rect x="0.5" y="0.5" width="439" height="315" rx="6" fill="#0D0D0F" stroke="#343438"/>
  <text x="25" y="35" class="heading">Open-source contributions</text>
  <text x="25" y="56" class="note">PUBLIC ACTIVITY · ALL TIME</text>
  {''.join(elements)}
  <path d="M25 253H415" stroke="#343438"/>
  <text x="25" y="274" class="note">External repos: PRs submitted to repositories you do not own.</text>
  <text x="25" y="296" class="note">Updated {escape(updated_at)} · Source: GitHub API</text>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="daniyyell-dev")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", args.username):
        parser.error("invalid GitHub username")
    stats = fetch_stats(args.username)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    snapshot = {"username": args.username, "updated_at": timestamp, "scope": "public, all time", **stats}
    # Fetch and validate everything before replacing either artifact.
    card = render_card(stats, timestamp)
    (ROOT / "assets/contribution-stats.svg").write_text(card, encoding="utf-8")
    (ROOT / "assets/contribution-stats.json").write_text(
        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
