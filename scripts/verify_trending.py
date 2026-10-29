#!/usr/bin/env python3
"""用 GitHub 官方 API 交叉核对抓取到的快照。

思路：Trending 页面上显示的 `52,287` 是该仓库的总 star 数，
独立去 https://api.github.com/repos/{owner}/{repo} 取 stargazers_count 比对。
官方页面 vs 官方 API，两条独立路径，能验证解析没有串行、没有抓错字段。

用法：
    python scripts/verify_trending.py             # 校验最新的周榜与月榜
    python scripts/verify_trending.py --limit 10  # 只校验前 N 条，省 API 配额
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "trending"
UA = "A-Bullrager-trending-verifier"

# 快照与 API 调用之间仓库仍在涨星，允许一个很小的漂移：
# 固定 20 星，或总星数的千分之一，取较大值。
DRIFT_FLOOR = 20
DRIFT_RATIO = 0.001


def drift_ok(snapshot: int, live: int) -> bool:
    allowed = max(DRIFT_FLOOR, int(live * DRIFT_RATIO))
    return 0 <= live - snapshot <= allowed


def api_stars(full_name: str) -> int | None:
    url = f"https://api.github.com/repos/{full_name}"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")).get("stargazers_count")
    except HTTPError as exc:
        if exc.code == 404:
            return -1
        if exc.code == 403:
            return -2
        return None
    except (URLError, TimeoutError, OSError):
        return None


def latest(kind: str) -> Path | None:
    files = sorted((DATA / kind).glob("*.json"))
    return files[-1] if files else None


def check(path: Path, limit: int = 0) -> tuple[int, int, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    repos = payload["repos"][:limit] if limit else payload["repos"]
    ok = bad = 0
    problems = []
    for repo in repos:
        live = api_stars(repo["full_name"])
        if live is None:
            problems.append(f"{repo['full_name']}: API 调用失败")
            bad += 1
            continue
        if live == -1:
            problems.append(f"{repo['full_name']}: 仓库不存在（可能改名或删除）")
            bad += 1
            continue
        if live == -2:
            problems.append("API 触发限流，停止校验")
            break
        diff = live - repo["stars"]
        if drift_ok(repo["stars"], live):
            ok += 1
        else:
            problems.append(
                f"{repo['full_name']}: 快照 {repo['stars']:,} vs 实时 {live:,} (差 {diff:+,})"
            )
            bad += 1
        time.sleep(0.6)
    return ok, bad, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="每个榜单只校验前 N 条")
    args = ap.parse_args()

    total_ok = total_bad = 0
    all_problems: list[str] = []

    for kind in ("weekly", "monthly"):
        path = latest(kind)
        if not path:
            print(f"[verify] {kind}: 没有快照，跳过")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        ok, bad, problems = check(path, args.limit)
        total_ok += ok
        total_bad += bad
        all_problems.extend(problems)
        print(f"[verify] {kind}/{path.name}: 一致 {ok} 条，异常 {bad} 条")

    print(f"[verify] 合计：一致 {total_ok} 条，异常 {total_bad} 条")
    for line in all_problems:
        print("  - " + line)
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
