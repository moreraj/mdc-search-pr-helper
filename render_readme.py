#!/usr/bin/env python3
"""Generate README.md as a live dashboard of open PRs in moodys-ma-mdc.

Runs `gh` queries for PRs across repos whose names contain `search`, `glue`,
or `ingestion` as a hyphen-delimited segment (with explicit exclusions), and
overwrites README.md with a markdown dashboard.

Environment: requires GH_TOKEN with `repo` + `read:org` (in CI), or a local
`gh auth login` session (when run by hand).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

ORG = "moodys-ma-mdc"
EXCLUDE_REPOS = {"mdc-data-etl-mwaa-operational-glue"}
README = Path(__file__).parent / "README.md"
NOW = dt.datetime.now(dt.timezone.utc)
REPO_PATTERN = re.compile(r"(^|-)(search|glue|ingestion)(-|$)")


def sh(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def list_matching_repos() -> list[str]:
    out = sh([
        "gh", "repo", "list", ORG, "--limit", "200",
        "--json", "name,isArchived",
        "--jq", '.[] | select(.isArchived==false) | .name',
    ])
    return [r for r in out.splitlines() if REPO_PATTERN.search(r) and r not in EXCLUDE_REPOS]


def repo_prs(repos: list[str]) -> list[dict]:
    flags: list[str] = []
    for r in repos:
        flags += ["--repo", f"{ORG}/{r}"]
    out = sh([
        "gh", "search", "prs", *flags,
        "--state", "open", "--limit", "100",
        "--json", "number,title,author,repository,url,isDraft,createdAt,updatedAt",
    ])
    return json.loads(out)


def team_search_url(repos: list[str]) -> str:
    parts = ["is:pr", "is:open"] + [f"repo:{ORG}/{r}" for r in repos]
    q = urllib.parse.quote(" ".join(parts))
    return f"https://github.com/search?q={q}&type=pullrequests&s=updated&o=desc"


def age(iso: str) -> tuple[str, int]:
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    delta = NOW - t
    days = delta.days
    if delta.total_seconds() / 3600 < 24:
        return ("today", 0)
    if days < 30:
        return (f"{days}d", days)
    if days < 60:
        return (f"~{round(days/7)}w", days)
    if days < 365:
        return (f"~{round(days/30)}mo", days)
    return (f"~{round(days/365)}y", days)


def trim(s: str, n: int = 70) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def render(repos: list[str], prs: list[dict]) -> str:
    today_count = stale = bots = drafts = 0
    for p in prs:
        _, days = age(p["updatedAt"])
        if days == 0:
            today_count += 1
        if days > 30:
            stale += 1
        if (p.get("author") or {}).get("login", "").endswith("[bot]"):
            bots += 1
        if p.get("isDraft"):
            drafts += 1

    groups: dict[str, list[dict]] = {}
    for p in prs:
        groups.setdefault(p["repository"]["name"], []).append(p)

    repos_sorted = sorted(
        groups, key=lambda r: max(p["updatedAt"] for p in groups[r]), reverse=True
    )

    lines: list[str] = []
    lines.append("# Search/Glue/Ingestion · open PRs")
    lines.append("")
    lines.append(
        f"_Auto-generated {NOW.strftime('%Y-%m-%d %H:%M UTC')} · "
        f"covers {len(repos)} repos in `{ORG}` · "
        f"excludes `{', '.join(sorted(EXCLUDE_REPOS))}`_"
    )
    lines.append("")
    lines.append(f"**[🔗 Open this view on GitHub search]({team_search_url(repos)})** — paste into Slack, pin in Confluence. Add `author:@me` to scope to yourself.")
    lines.append("")
    lines.append(
        f"**Stats:** {today_count} active today · {stale} stale (>30d) · "
        f"{bots} dependabot · {drafts} drafts · **{len(prs)} total**"
    )
    lines.append("")

    if not prs:
        lines.append("_No open PRs in matching repos._")
        return "\n".join(lines) + "\n"

    for repo in repos_sorted:
        repo_prs_list = sorted(groups[repo], key=lambda p: p["updatedAt"], reverse=True)
        lines.append(f"<details><summary><b>{repo}</b> · {len(repo_prs_list)} PRs</summary>")
        lines.append("")
        lines.append("| PR | Title | Author | Age |")
        lines.append("|---|---|---|---|")
        for p in repo_prs_list:
            label, days = age(p["updatedAt"])
            author = (p.get("author") or {}).get("login", "")
            title = trim(p["title"])
            if p.get("isDraft"):
                title += " _(draft)_"
            age_cell = f"**{label}**" if days == 0 else label
            lines.append(
                f"| [#{p['number']}]({p['url']}) "
                f"| {md_escape(title)} "
                f"| `{author}` "
                f"| {age_cell} |"
            )
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Also list repos with no open PRs, for visibility
    quiet = [r for r in repos if r not in groups]
    if quiet:
        lines.append(f"<sub>Repos with no open PRs: {', '.join(f'`{r}`' for r in quiet)}</sub>")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Refresh schedule: every 30 min via [`.github/workflows/refresh.yml`](.github/workflows/refresh.yml). "
                 "To force a refresh, run the workflow manually from the Actions tab.")
    return "\n".join(lines) + "\n"


def main() -> int:
    repos = list_matching_repos()
    prs = [p for p in repo_prs(repos) if p["repository"]["name"] in repos]
    README.write_text(render(repos, prs), encoding="utf-8")
    print(f"wrote {README}")
    print(f"  repos: {len(repos)}  prs: {len(prs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
