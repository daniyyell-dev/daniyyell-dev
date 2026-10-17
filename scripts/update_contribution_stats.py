#!/usr/bin/env python3
"""Generate a public GitHub activity card from GitHub's GraphQL API.

Requires the GitHub CLI and an authenticated GH_TOKEN (GITHUB_TOKEN in Actions).
External repositories means distinct non-owned repositories receiving authored PRs.
Only public activity is aggregated or written; private repository details are discarded.
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


def fetch_stats(username: str) -> dict:
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
        **fetch_profile_stats(username),
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


PROFILE_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    contributionsCollection {
      startedAt endedAt
      commitContributionsByRepository(maxRepositories:100) {
        repository { isPrivate nameWithOwner } contributions { totalCount }
      }
      issueContributionsByRepository(maxRepositories:100) { repository { isPrivate nameWithOwner } }
      pullRequestContributionsByRepository(maxRepositories:100) { repository { isPrivate nameWithOwner } }
      pullRequestReviewContributionsByRepository(maxRepositories:100) { repository { isPrivate nameWithOwner } }
    }
    repositories(first:100, after:$cursor, ownerAffiliations:OWNER, privacy:PUBLIC, isFork:false) {
      nodes { stargazerCount } pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def fetch_profile_stats(username: str) -> dict:
    cursor = None
    stars = 0
    while True:
        command = ["gh", "api", "graphql", "-f", f"query={PROFILE_QUERY}", "-f", f"login={username}"]
        if cursor:
            command.extend(["-f", f"cursor={cursor}"])
        response = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        if response.get("errors") or not response.get("data", {}).get("user"):
            raise RuntimeError("Incomplete GitHub profile response; keeping the previous card")
        user = response["data"]["user"]
        repositories = user["repositories"]
        stars += sum(repo["stargazerCount"] for repo in repositories["nodes"])
        if not repositories["pageInfo"]["hasNextPage"]:
            break
        cursor = repositories["pageInfo"]["endCursor"]
    collection = user["contributionsCollection"]
    groups = [collection[key] for key in (
        "commitContributionsByRepository", "issueContributionsByRepository",
        "pullRequestContributionsByRepository", "pullRequestReviewContributionsByRepository",
    )]
    if any(len(group) >= 100 for group in groups):
        raise RuntimeError("Contribution repository limit reached; refusing a truncated card")
    public_repos = {item["repository"]["nameWithOwner"] for group in groups for item in group
                    if not item["repository"]["isPrivate"]}
    return {
        "stars_earned": stars,
        "commits_last_year": sum(item["contributions"]["totalCount"] for item in groups[0]
                                 if not item["repository"]["isPrivate"]),
        "contributed_repositories_last_year": len(public_repos),
        "contribution_period_start": collection["startedAt"],
        "contribution_period_end": collection["endedAt"],
    }


def render_card(stats: dict, updated_at: str) -> str:
    rows = [
        ("Total Stars Earned", stats["stars_earned"], "m11 1 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z"),
        ("Total Commits (last year)", stats["commits_last_year"], "M1 11h6m8 0h6M7 11a4 4 0 1 0 8 0a4 4 0 1 0-8 0"),
        ("Total PRs", stats["pull_requests"], "M5 3v12m0-9h7a4 4 0 0 1 4 4v5M2 3a3 3 0 1 0 6 0a3 3 0 1 0-6 0M2 18a3 3 0 1 0 6 0a3 3 0 1 0-6 0M13 18a3 3 0 1 0 6 0a3 3 0 1 0-6 0"),
        ("Merged PRs", stats["merged_pull_requests"], "M5 3v12m0-9c0 5 11 3 11 9M2 3a3 3 0 1 0 6 0a3 3 0 1 0-6 0M2 18a3 3 0 1 0 6 0a3 3 0 1 0-6 0M13 18a3 3 0 1 0 6 0a3 3 0 1 0-6 0"),
        ("Open PRs", stats["open_pull_requests"], "M5 3v12m11-9v9m-4-11 4-4 4 4M2 3a3 3 0 1 0 6 0a3 3 0 1 0-6 0M2 18a3 3 0 1 0 6 0a3 3 0 1 0-6 0M13 18a3 3 0 1 0 6 0a3 3 0 1 0-6 0"),
        ("Total Issues", stats["issues_opened"], "M11 1a10 10 0 1 0 0 20a10 10 0 1 0 0-20M11 6v6m0 4v.1"),
        ("Contributed to (last year)", stats["contributed_repositories_last_year"], "M4 1h14v19H4a3 3 0 0 1 0-6h14M4 1a3 3 0 0 0-3 3v13m5 0v5l3-2 3 2v-5"),
        ("External repos with PRs", stats["external_repositories"], "M4 1h14v19H4a3 3 0 0 1 0-6h14M4 1a3 3 0 0 0-3 3v13m5 0v5l3-2 3 2v-5"),
    ]
    description = "; ".join(f"{label}: {value}" for label, value, _ in rows)
    description += f". Public activity. Commits and contributed repositories use GitHub’s last-year window; PRs and issues are all time. Updated {updated_at}."
    elements = []
    for index, (label, value, icon) in enumerate(rows):
        y = 89 + index * 37
        elements.append(
            f'<path d="{icon}" transform="translate(27 {y-17}) scale(.85)" fill="none" stroke="#FF2020" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<text x="62" y="{y}" class="stat">{escape(label)}:</text>'
            f'<text x="489" y="{y}" class="stat" text-anchor="end">{value:,}</text>'
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="520" height="379" viewBox="0 0 520 379" role="img" aria-labelledby="title desc">
  <title id="title">Daniel Jeremiah's GitHub Stats</title>
  <desc id="desc">{escape(description)}</desc>
  <style>
    text {{ font-family: 'Segoe UI', Ubuntu, sans-serif; }}
    .heading {{ fill: #FF2020; font-size: 21px; font-weight: 700; }}
    .stat {{ fill: #E5E7EB; font-size: 16px; font-weight: 650; }}
  </style>
  <rect x=".75" y=".75" width="518.5" height="377.5" rx="6" fill="#0D0D0F" stroke="#343438" stroke-width="1.5"/>
  <text x="27" y="40" class="heading">Daniel Jeremiah's GitHub Stats</text>
  {''.join(elements)}
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
    snapshot = {"username": args.username, "updated_at": timestamp, "scope": "public; PRs/issues all time, commits/contributed repositories last year", **stats}
    # Fetch and validate everything before replacing either artifact.
    card = render_card(stats, timestamp)
    (ROOT / "assets/github-contributions.svg").write_text(card, encoding="utf-8")
    (ROOT / "assets/github-stats.svg").write_text(card, encoding="utf-8")
    (ROOT / "assets/contribution-stats.json").write_text(
        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
