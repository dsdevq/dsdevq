#!/usr/bin/env python3
"""Render the profile README graphs into metrics/*.svg.

Public data only, standard library only. Works with no token (for local
runs) or with GITHUB_TOKEN (for the scheduled workflow, which gets a higher
rate limit). Anything archived, forked or private is left out, so the
graphs describe current, owned work across the user and the org.
"""
import html
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER = "dsdevq"
ORG = "lifekit-hq"
# Auto-synced LeetCode solutions are not authored work.
IGNORED_REPOS = {"neetcode-submissions"}
OUT_DIR = Path(__file__).resolve().parent.parent / "metrics"

TOKEN = os.environ.get("GITHUB_TOKEN", "")
# Search allows 10 requests/min unauthenticated, 30 with a token.
SEARCH_PAUSE = 2.5 if TOKEN else 6.5

BG, BORDER = "#1a1b26", "#2f334d"
TITLE, TEXT, MUTED, ACCENT, VIOLET = "#7aa2f7", "#c0caf5", "#7982a9", "#7aa2f7", "#bb9af7"
LANG_COLORS = {
    "C#": "#178600", "TypeScript": "#3178c6", "Python": "#3572A5", "Shell": "#89e051",
    "JavaScript": "#f1e05a", "HTML": "#e34c26", "CSS": "#563d7c", "SCSS": "#c6538c",
    "Dockerfile": "#384d54", "Bicep": "#519aba", "Go": "#00ADD8", "PowerShell": "#012456",
}
FALLBACK = ["#7dcfff", "#e0af68", "#9ece6a", "#f7768e", "#bb9af7", "#7aa2f7"]
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"


def get(url, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "User-Agent": "dsdevq-profile-metrics"}
    if TOKEN and url.startswith("https://api.github.com"):
        headers["Authorization"] = f"Bearer {TOKEN}"
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as res:
                return res.read().decode()
        except HTTPError as err:
            if err.code in (403, 429) and attempt < 3:
                time.sleep(20 * (attempt + 1))
                continue
            raise


def api(path, **params):
    query = f"?{urlencode(params)}" if params else ""
    return json.loads(get(f"https://api.github.com{path}{query}"))


def paged(path, **params):
    items, page = [], 1
    while True:
        chunk = api(path, per_page=100, page=page, **params)
        items += chunk
        if len(chunk) < 100:
            return items
        page += 1


def search_total(kind, query):
    time.sleep(SEARCH_PAUSE)
    return api(f"/search/{kind}", q=query, per_page=1)["total_count"]


def active_repos():
    repos = paged(f"/users/{USER}/repos", type="owner") + paged(f"/orgs/{ORG}/repos", type="public")
    return [
        r for r in repos
        if not (r["fork"] or r["archived"] or r["private"] or r["name"] in IGNORED_REPOS)
    ]


def language_bytes(repos):
    total = Counter()
    for repo in repos:
        total.update(api(f"/repos/{repo['full_name']}/languages"))
    return total


def contribution_days():
    page = get(f"https://github.com/users/{USER}/contributions", accept="text/html")
    cells = re.findall(r'data-date="(\d{4}-\d{2}-\d{2})" id="(contribution-day-component-\d+-\d+)"', page)
    tips = dict(re.findall(r'for="(contribution-day-component-\d+-\d+)"[^>]*>\s*([^<]*?)\s*</tool-tip>', page))
    days = {}
    for day, cell in cells:
        found = re.match(r"(\d+) contribution", tips.get(cell, ""))
        days[date.fromisoformat(day)] = int(found.group(1)) if found else 0
    return {d: n for d, n in days.items() if d <= date.today()}


def streaks(days):
    longest = run = 0
    for day in sorted(days):
        run = run + 1 if days[day] else 0
        longest = max(longest, run)
    current, day = 0, date.today()
    if not days.get(day):
        day -= timedelta(days=1)
    while days.get(day):
        current += 1
        day -= timedelta(days=1)
    return current, longest


def esc(value):
    return html.escape(str(value), quote=True)


def card(title, subtitle, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="250" viewBox="0 0 480 250" role="img" aria-label="{esc(title)}">
  <title>{esc(title)}</title>
  <rect x="0.5" y="0.5" width="479" height="249" rx="10" fill="{BG}" stroke="{BORDER}"/>
  <g font-family="{FONT}">
    <text x="24" y="36" font-size="16" font-weight="600" fill="{TITLE}">{esc(title)}</text>
    <text x="24" y="55" font-size="11" fill="{MUTED}">{esc(subtitle)}</text>
{body}
  </g>
</svg>
"""


def fmt(number):
    return f"{number:,}"


def languages_card(repos):
    sizes = language_bytes(repos)
    total = sum(sizes.values())
    top = sizes.most_common(7)
    rest = total - sum(size for _, size in top)
    rows = [(name, size) for name, size in top] + ([("Other", rest)] if rest > 0 else [])
    colors, spare = {}, iter(FALLBACK * 2)
    for name, _ in rows:
        colors[name] = LANG_COLORS.get(name) or ("#565f89" if name == "Other" else next(spare))

    bar, x = [], 24.0
    for name, size in rows:
        width = 432 * size / total
        bar.append(f'<rect x="{x:.1f}" y="70" width="{max(width, 1):.1f}" height="12" fill="{colors[name]}"/>')
        x += width
    legend = []
    for i, (name, size) in enumerate(rows):
        col, row = divmod(i, 4)
        lx, ly = 24 + col * 228, 114 + row * 32
        legend.append(
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{colors[name]}"/>'
            f'<text x="{lx + 18}" y="{ly}" font-size="13" fill="{TEXT}">{esc(name)}</text>'
            f'<text x="{lx + 204}" y="{ly}" font-size="13" fill="{MUTED}" text-anchor="end">{100 * size / total:.1f}%</text>'
        )
    body = (
        '<clipPath id="bar"><rect x="24" y="70" width="432" height="12" rx="6"/></clipPath>'
        f'<g clip-path="url(#bar)">{"".join(bar)}</g>{"".join(legend)}'
    )
    subtitle = f"{USER} + {ORG} - {len(repos)} active repos by bytes, forks and archived excluded"
    return card("Languages - current work", subtitle, body)


def stats_card(repos, days):
    current, longest = streaks(days)
    items = [
        (fmt(len(repos)), "Active public repos"),
        (fmt(sum(r["stargazers_count"] for r in repos)), "Stars earned"),
        (fmt(search_total("commits", f"author:{USER}")), "Commits (default branches)"),
        (fmt(search_total("issues", f"author:{USER} type:pr")), "Pull requests opened"),
        (fmt(search_total("issues", f"author:{USER} type:pr is:merged")), "Pull requests merged"),
        (fmt(search_total("issues", f"author:{USER} type:pr org:{ORG}")), f"Pull requests in {ORG}"),
        (f"{current} days", "Current streak"),
        (f"{longest} days", "Longest streak, 12 months"),
    ]
    cells = []
    for i, (value, label) in enumerate(items):
        col, row = divmod(i, 4)
        x, y = 24 + col * 228, 88 + row * 44
        cells.append(
            f'<text x="{x}" y="{y}" font-size="22" font-weight="700" fill="{ACCENT if col == 0 else VIOLET}">{esc(value)}</text>'
            f'<text x="{x}" y="{y + 16}" font-size="11" fill="{MUTED}">{esc(label)}</text>'
        )
    return card("GitHub stats", "Public activity, all-time unless noted", "\n".join(cells))


def lifekit_card(repos):
    counts = []
    for repo in repos:
        if repo["owner"]["login"] != ORG:
            continue
        total = search_total("issues", f"author:{USER} type:pr repo:{repo['full_name']}")
        if total:
            counts.append((repo["name"], total, repo["language"]))
    counts = sorted(counts, key=lambda item: -item[1])[:7]
    top = counts[0][1]
    rows = []
    for i, (name, total, language) in enumerate(counts):
        y = 92 + i * 22
        width = max(4, 200 * total / top)
        color = LANG_COLORS.get(language, VIOLET)
        weight = "700" if name == "finance-sentry" else "400"
        rows.append(
            f'<text x="24" y="{y}" font-size="13" font-weight="{weight}" fill="{TEXT}">{esc(name)}</text>'
            f'<rect x="170" y="{y - 11}" width="{width:.1f}" height="12" rx="3" fill="{color}"/>'
            f'<text x="{170 + width + 8:.1f}" y="{y}" font-size="12" fill="{MUTED}">{fmt(total)}</text>'
        )
    return card(f"{ORG} - where the work happens", "Pull requests authored, per public repo", "\n".join(rows))


def contributions_card(days):
    month = date.today().replace(day=1)
    months = []
    for _ in range(12):
        months.append(month)
        month = (month - timedelta(days=1)).replace(day=1)
    months.reverse()
    per_month = Counter()
    for day, count in days.items():
        per_month[day.replace(day=1)] += count
    peak = max(per_month[m] for m in months) or 1
    busiest_day = max(days, key=days.get)
    bars = []
    for i, m in enumerate(months):
        x, value = 24 + i * 36, per_month[m]
        height = max(2, 112 * value / peak)
        bars.append(
            f'<rect x="{x}" y="{208 - height:.1f}" width="26" height="{height:.1f}" rx="3" fill="{VIOLET if m == months[-1] else ACCENT}"/>'
            f'<text x="{x + 13}" y="{202 - height:.1f}" font-size="10" fill="{MUTED}" text-anchor="middle">{value}</text>'
            f'<text x="{x + 13}" y="226" font-size="10" fill="{MUTED}" text-anchor="middle">{m.strftime("%b")}</text>'
        )
    subtitle = f"{fmt(sum(days.values()))} in the last year - busiest day {days[busiest_day]} on {busiest_day:%d %b %Y}"
    return card("Contributions - last 12 months", subtitle, "\n".join(bars))


def main():
    OUT_DIR.mkdir(exist_ok=True)
    repos = active_repos()
    days = contribution_days()
    if not days or sum(days.values()) == 0:
        sys.exit("contribution calendar came back empty or all zero")
    cards = {
        "languages.svg": languages_card(repos),
        "stats.svg": stats_card(repos, days),
        "lifekit.svg": lifekit_card(repos),
        "contributions.svg": contributions_card(days),
    }
    for name, svg in cards.items():
        (OUT_DIR / name).write_text(svg)
        print(f"wrote metrics/{name}")


if __name__ == "__main__":
    main()
