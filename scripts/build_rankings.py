#!/usr/bin/env python3
"""聚合产物 + 索引文件。

周榜、月榜都直接来自 GitHub 官方页面；GitHub 没有「年度」榜，
所以年榜由当年的月度快照聚合（各月 star 新增累加），口径已在页面标注。

输出：
    data/trending/yearly/YYYY.json
    data/trending/index.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "trending"
WEEKLY = DATA / "weekly"
MONTHLY = DATA / "monthly"
YEARLY = DATA / "yearly"
LIMIT = 50


def read_dir(path: Path) -> list[dict]:
    items = []
    for file in sorted(path.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[build] 跳过损坏文件 {file.name}: {exc}", file=sys.stderr)
            continue
        if data.get("repos"):
            items.append(data)
    return items


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[build] {path.relative_to(ROOT)}")


def aggregate_months(months: list[dict], limit: int = LIMIT) -> list[dict]:
    bucket: dict[str, dict] = {}
    for month in months:
        for repo in month["repos"]:
            key = repo["full_name"]
            item = bucket.get(key)
            if item is None:
                item = {
                    "full_name": key,
                    "owner": repo["owner"],
                    "name": repo["name"],
                    "url": repo["url"],
                    "description": repo["description"],
                    "language": repo["language"],
                    "language_color": repo["language_color"],
                    "stars": repo["stars"],
                    "stars_period_total": 0,
                    "appearances": 0,
                    "best_rank": repo["rank"],
                    "months": [],
                }
                bucket[key] = item
            item["stars_period_total"] += repo["stars_period"]
            item["appearances"] += 1
            item["best_rank"] = min(item["best_rank"], repo["rank"])
            item["months"].append(month["period"])
            item["stars"] = max(item["stars"], repo["stars"])
            if repo["description"]:
                item["description"] = repo["description"]
            if repo["language"]:
                item["language"] = repo["language"]
                item["language_color"] = repo["language_color"] or item["language_color"]

    ranked = sorted(
        bucket.values(),
        key=lambda r: (r["stars_period_total"], r["stars"]),
        reverse=True,
    )[:limit]
    for i, repo in enumerate(ranked, 1):
        repo["rank"] = i
    return ranked


def main() -> int:
    weeks = read_dir(WEEKLY)
    months = read_dir(MONTHLY)

    if not weeks and not months:
        print("[build] 没有任何快照，先跑 fetch_trending.py", file=sys.stderr)
        return 1

    by_year: dict[str, list[dict]] = {}
    for month in months:
        by_year.setdefault(month["period"][:4], []).append(month)

    for year, items in sorted(by_year.items()):
        items.sort(key=lambda m: m["period"])
        write_json(
            YEARLY / f"{year}.json",
            {
                "period": year,
                "kind": "yearly",
                "months": len(items),
                "month_labels": [m["period"] for m in items],
                "updated_at": items[-1]["captured_at"],
                "note": "由当年的官方月度榜聚合，各月 star 新增累加",
                "repos": aggregate_months(items),
            },
        )

    updated = max(
        [w["captured_at"] for w in weeks] + [m["captured_at"] for m in months]
    )

    write_json(
        DATA / "index.json",
        {
            "updated_at": updated,
            "weeks": [
                {
                    "date": w["period"],
                    "captured_at": w["captured_at"],
                    "count": len(w["repos"]),
                    "top": w["repos"][0]["full_name"] if w["repos"] else "",
                }
                for w in sorted(weeks, key=lambda x: x["period"], reverse=True)
            ],
            "months": [
                {
                    "period": m["period"],
                    "captured_at": m["captured_at"],
                    "count": len(m["repos"]),
                    "top": m["repos"][0]["full_name"] if m["repos"] else "",
                }
                for m in sorted(months, key=lambda x: x["period"], reverse=True)
            ],
            "years": sorted(by_year.keys(), reverse=True),
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
