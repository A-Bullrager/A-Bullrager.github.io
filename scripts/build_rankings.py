#!/usr/bin/env python3
"""把周快照聚合成月榜 / 年榜，并生成索引文件。

口径：榜单按「上榜各周的 star 新增之和」排序（stars_week 累加），
     并记录上榜次数与最高单周表现。周榜是唯一事实来源，聚合结果可随时重建。

输出：
    data/trending/index.json
    data/trending/monthly/YYYY-MM.json
    data/trending/yearly/YYYY.json
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


def load_weeks() -> list[dict]:
    files = sorted(WEEKLY.glob("*.json"))
    weeks = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[build] 跳过损坏文件 {path.name}: {exc}", file=sys.stderr)
            continue
        if data.get("repos"):
            weeks.append(data)
    weeks.sort(key=lambda w: w["captured_at"])
    return weeks


def aggregate(weeks: list[dict], limit: int = LIMIT) -> list[dict]:
    bucket: dict[str, dict] = {}
    for week in weeks:
        for repo in week["repos"]:
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
                    "stars_week_total": 0,
                    "stars_week_max": 0,
                    "appearances": 0,
                    "best_rank": repo["rank"],
                    "weeks": [],
                }
                bucket[key] = item
            item["stars_week_total"] += repo["stars_week"]
            item["stars_week_max"] = max(item["stars_week_max"], repo["stars_week"])
            item["appearances"] += 1
            item["best_rank"] = min(item["best_rank"], repo["rank"])
            item["weeks"].append(week["captured_at"])
            item["stars"] = max(item["stars"], repo["stars"])
            if repo["description"]:
                item["description"] = repo["description"]
            if repo["language"]:
                item["language"] = repo["language"]
                item["language_color"] = repo["language_color"] or item["language_color"]

    ranked = sorted(
        bucket.values(),
        key=lambda r: (r["stars_week_total"], r["stars_week_max"], r["stars"]),
        reverse=True,
    )[:limit]
    for i, repo in enumerate(ranked, 1):
        repo["rank"] = i
    return ranked


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[build] {path.relative_to(ROOT)}")


def main() -> int:
    weeks = load_weeks()
    if not weeks:
        print("[build] data/trending/weekly 下没有快照，先跑 fetch_trending.py", file=sys.stderr)
        return 1

    by_month: dict[str, list[dict]] = {}
    by_year: dict[str, list[dict]] = {}
    for week in weeks:
        day = week["captured_at"]
        by_month.setdefault(day[:7], []).append(week)
        by_year.setdefault(day[:4], []).append(week)

    for period, items in sorted(by_month.items()):
        write_json(
            MONTHLY / f"{period}.json",
            {
                "period": period,
                "kind": "monthly",
                "weeks": len(items),
                "updated_at": items[-1]["captured_at"],
                "source": items[-1]["source"],
                "repos": aggregate(items),
            },
        )

    for period, items in sorted(by_year.items()):
        write_json(
            YEARLY / f"{period}.json",
            {
                "period": period,
                "kind": "yearly",
                "weeks": len(items),
                "updated_at": items[-1]["captured_at"],
                "source": items[-1]["source"],
                "repos": aggregate(items),
            },
        )

    write_json(
        DATA / "index.json",
        {
            "updated_at": weeks[-1]["captured_at"],
            "source": weeks[-1]["source"],
            "weeks": [
                {
                    "date": w["captured_at"],
                    "count": len(w["repos"]),
                    "top": w["repos"][0]["full_name"] if w["repos"] else "",
                }
                for w in reversed(weeks)
            ],
            "months": sorted(by_month.keys(), reverse=True),
            "years": sorted(by_year.keys(), reverse=True),
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
