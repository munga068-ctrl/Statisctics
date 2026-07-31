"""
Pulls data from the INDICES LOG Notion database (plus its RTH PROFILES and
DIRECTION lookup databases), computes first-hour (AM DR / 9:30-10:30) HOD/LOD
statistics, and writes the result to data/stats.json for the dashboard to read.

Requires an environment variable NOTION_API_KEY with a Notion internal
integration token that has been shared with all three databases below.
"""

import os
import json
from datetime import datetime, timezone

import requests

NOTION_VERSION = "2025-09-03"

# Data source IDs (from the Kewa/MMTrades Notion workspace).
INDICES_LOG_DS = "28cf7bb7-7d6d-80d1-94ef-000b834cefb7"
RTH_PROFILES_DS = "2a2f7bb7-7d6d-8060-87ab-000b509a9589"
DIRECTION_DS = "33af7bb7-7d6d-80b1-bd2e-000bf31c2649"


def get_headers():
    token = os.environ.get("NOTION_API_KEY")
    if not token:
        raise RuntimeError("NOTION_API_KEY environment variable is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def query_all(data_source_id, headers):
    """Paginate through every row in a Notion data source."""
    results = []
    url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"
    payload = {"page_size": 100}
    while True:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data["results"])
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return results


def get_title(props, name):
    prop = props.get(name)
    if not prop:
        return None
    for t in prop.get("title", []):
        return t.get("plain_text")
    return None


def get_relation_ids(props, name):
    prop = props.get(name)
    if not prop:
        return []
    return [r["id"] for r in prop.get("relation", [])]


def main():
    headers = get_headers()

    # Build id -> name lookup maps for the two related "option" databases.
    profile_map = {
        p["id"]: get_title(p["properties"], "Name")
        for p in query_all(RTH_PROFILES_DS, headers)
    }
    direction_map = {
        p["id"]: get_title(p["properties"], "Name")
        for p in query_all(DIRECTION_DS, headers)
    }

    log_pages = query_all(INDICES_LOG_DS, headers)

    total_days = 0
    profile_counts = {}
    first_hour_hod_count = 0
    first_hour_lod_count = 0
    both_first_hour_count = 0
    direction_totals = {}
    direction_first_hour_hod = {}
    direction_first_hour_lod = {}

    for page in log_pages:
        props = page["properties"]
        rth_ids = get_relation_ids(props, "RTH PROFILES")
        dir_ids = get_relation_ids(props, "DIRECTION")

        if not rth_ids:
            continue  # skip days that haven't been tagged with a profile yet

        total_days += 1

        profile_name = profile_map.get(rth_ids[0]) or "Unknown"
        profile_counts[profile_name] = profile_counts.get(profile_name, 0) + 1

        # "AM DR" and "AM ADR" both refer to the first-hour (9:30-10:30) window.
        is_hod_first_hour = "DR High HOD" in profile_name
        is_lod_first_hour = "DR Low LOD" in profile_name

        if is_hod_first_hour:
            first_hour_hod_count += 1
        if is_lod_first_hour:
            first_hour_lod_count += 1
        if is_hod_first_hour and is_lod_first_hour:
            both_first_hour_count += 1

        directions_today = [direction_map.get(d) or "Unknown" for d in dir_ids] or ["Unknown"]
        for d in directions_today:
            direction_totals[d] = direction_totals.get(d, 0) + 1
            if is_hod_first_hour:
                direction_first_hour_hod[d] = direction_first_hour_hod.get(d, 0) + 1
            if is_lod_first_hour:
                direction_first_hour_lod[d] = direction_first_hour_lod.get(d, 0) + 1

    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_days": total_days,
        "first_hour_hod_count": first_hour_hod_count,
        "first_hour_lod_count": first_hour_lod_count,
        "both_first_hour_count": both_first_hour_count,
        "profile_counts": dict(
            sorted(profile_counts.items(), key=lambda kv: kv[1], reverse=True)
        ),
        "direction_totals": direction_totals,
        "direction_first_hour_hod": direction_first_hour_hod,
        "direction_first_hour_lod": direction_first_hour_lod,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    print(f"Wrote data/stats.json — {total_days} days processed.")


if __name__ == "__main__":
    main()
