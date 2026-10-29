#!/usr/bin/env python3
"""抓取 GitHub Trending 官方榜单，保存为快照。

支持两个官方口径：
    --since weekly   周榜（滚动 7 天）  -> data/trending/weekly/YYYY-MM-DD.json
    --since monthly  月榜（滚动 30 天） -> data/trending/monthly/YYYY-MM.json

月榜快照在每月 1 号抓取时代表「上一个月」，其余日期代表「当月」。

用法：
    python scripts/fetch_trending.py --since weekly
    python scripts/fetch_trending.py --since monthly --html local.html   # 离线调试
"""
import argparse
import html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "trending"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

LABELS = {"weekly": ("week", "本周"), "monthly": ("month", "本月")}


def source_url(since: str) -> str:
    return f"https://github.com/trending?since={since}"


def fetch(url: str, tries: int = 4) -> str:
    last = None
    for i in range(tries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urlopen(req, timeout=45) as resp:
                return resp.read().decode("utf-8", "replace")
        except (URLError, TimeoutError, OSError) as exc:
            last = exc
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    raise SystemExit(f"[fetch] 抓取失败：{last}")


def text_of(fragment: str) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def to_int(raw: str) -> int:
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else 0


def parse_repo(block: str, rank: int, since: str) -> dict | None:
    head = block.find('<h2 class="h3 lh-condensed">')
    if head < 0:
        return None
    m = re.search(r'href="/([^"/]+)/([^"/]+)"', block[head:])
    if not m:
        return None
    owner, name = m.group(1), m.group(2)

    desc = ""
    md = re.search(r'<p class="col-9 color-fg-muted[^"]*">(.*?)</p>', block, re.S)
    if md:
        desc = text_of(md.group(1))

    lang, color = "", ""
    ml = re.search(r'itemprop="programmingLanguage">([^<]+)<', block)
    if ml:
        lang = text_of(ml.group(1))
        mc = re.search(
            r'repo-language-color"\s+style="background-color:\s*(#[0-9a-fA-F]{3,8})',
            block,
        )
        if mc:
            color = mc.group(1)

    stars = forks = 0
    ms = re.search(r'href="[^"]*/stargazers"[^>]*>(.*?)</a>', block, re.S)
    if ms:
        stars = to_int(text_of(ms.group(1)))
    mf = re.search(r'href="[^"]*/forks"[^>]*>(.*?)</a>', block, re.S)
    if mf:
        forks = to_int(text_of(mf.group(1)))

    label = "week" if since == "weekly" else "month"
    period_gain = 0
    mg = re.search(r"([\d,]+)\s+stars?\s+this\s+" + label, block, re.I)
    if mg:
        period_gain = to_int(mg.group(1))

    return {
        "rank": rank,
        "full_name": f"{owner}/{name}",
        "owner": owner,
        "name": name,
        "url": f"https://github.com/{owner}/{name}",
        "description": desc,
        "language": lang,
        "language_color": color,
        "stars": stars,
        "forks": forks,
        "stars_period": period_gain,
    }


def parse(page: str, since: str) -> list[dict]:
    blocks = page.split('<article class="Box-row">')[1:]
    repos, seen = [], set()
    for block in blocks:
        repo = parse_repo(block, len(repos) + 1, since)
        if not repo or repo["full_name"] in seen:
            continue
        seen.add(repo["full_name"])
        repos.append(repo)
    return repos


def target_path(since: str, captured: date) -> tuple[Path, str]:
    """返回 (输出路径, 期数标识)。"""
    if since == "monthly":
        period = captured
        if captured.day == 1:
            period = captured - timedelta(days=1)
        key = period.strftime("%Y-%m")
        return DATA / "monthly" / f"{key}.json", key
    key = captured.strftime("%Y-%m-%d")
    return DATA / "weekly" / f"{key}.json", key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", choices=["weekly", "monthly"], default="weekly")
    ap.add_argument("--html", help="从本地 HTML 文件读取，而不是联网抓取")
    ap.add_argument("--date", help="覆盖抓取日期 YYYY-MM-DD（调试用）")
    args = ap.parse_args()

    if args.html:
        page = Path(args.html).read_text(encoding="utf-8", errors="replace")
    else:
        page = fetch(source_url(args.since))

    repos = parse(page, args.since)
    if not repos:
        print("[fetch] 解析到 0 个仓库，页面结构可能已变化", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    captured = date.fromisoformat(args.date) if args.date else now.date()
    out, key = target_path(args.since, captured)

    payload = {
        "captured_at": captured.isoformat(),
        "captured_iso": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since": args.since,
        "period": key,
        "source": source_url(args.since),
        "count": len(repos),
        "repos": repos,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[fetch] {args.since}: {len(repos)} 个仓库 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
