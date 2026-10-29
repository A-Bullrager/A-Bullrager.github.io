#!/usr/bin/env python3
"""抓取 GitHub Trending 周榜，保存为一份不可变的周快照。

用法：
    python scripts/fetch_trending.py            # 联网抓取
    python scripts/fetch_trending.py --html f   # 从本地 HTML 文件解析（调试用）

输出：data/trending/weekly/YYYY-MM-DD.json
"""
import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

SOURCE = "https://github.com/trending?since=weekly"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "trending" / "weekly"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


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
    """去掉标签、反转义、压缩空白。"""
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def to_int(raw: str) -> int:
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else 0


def parse_repo(block: str, rank: int) -> dict | None:
    head = block.find('<h2 class="h3 lh-condensed">')
    if head < 0:
        return None
    after = block[head:]
    m = re.search(r'href="/([^"/]+)/([^"/]+)"', after)
    if not m:
        return None
    owner, name = m.group(1), m.group(2)

    desc = ""
    md = re.search(
        r'<p class="col-9 color-fg-muted[^"]*">(.*?)</p>', block, re.S
    )
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

    week = 0
    mw = re.search(r"([\d,]+)\s+stars?\s+this\s+week", block, re.I)
    if mw:
        week = to_int(mw.group(1))

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
        "stars_week": week,
    }


def parse(page: str) -> list[dict]:
    blocks = page.split('<article class="Box-row">')[1:]
    repos, seen = [], set()
    for block in blocks:
        repo = parse_repo(block, len(repos) + 1)
        if not repo or repo["full_name"] in seen:
            continue
        seen.add(repo["full_name"])
        repos.append(repo)
    return repos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", help="从本地 HTML 文件读取，而不是联网抓取")
    args = ap.parse_args()

    if args.html:
        page = Path(args.html).read_text(encoding="utf-8", errors="replace")
    else:
        page = fetch(SOURCE)

    repos = parse(page)
    if not repos:
        print("[fetch] 解析到 0 个仓库，页面结构可能已变化", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    payload = {
        "captured_at": now.strftime("%Y-%m-%d"),
        "captured_iso": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since": "weekly",
        "source": SOURCE,
        "count": len(repos),
        "repos": repos,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{payload['captured_at']}.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[fetch] {len(repos)} 个仓库 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
