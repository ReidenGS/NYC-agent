from __future__ import annotations

from pathlib import Path

from app.config import settings


COMMON_REFERENCES = [
    "references/common-sql-rules.md",
    "references/common-output-contract.md",
    "references/common-area-contract.md",
]

TASK_REFERENCE_MAP = {
    "neighborhood.entertainment_query": [
        "references/intent-neighborhood-entertainment.md",
        "references/table-app-area-dimension.md",
        "references/table-app-area-entertainment-category-daily.md",
        "references/table-app-map-poi-snapshot.md",
    ],
    "neighborhood.convenience_query": [
        "references/intent-neighborhood-convenience.md",
        "references/table-app-area-dimension.md",
        "references/table-app-area-convenience-category-daily.md",
        "references/table-app-map-poi-snapshot.md",
    ],
    "housing.rent_query": [
        "references/intent-housing-rent.md",
        "references/table-app-area-dimension.md",
        "references/table-app-area-rental-market-daily.md",
        "references/table-app-area-rent-benchmark-monthly.md",
        "references/table-app-area-rental-listing-snapshot.md",
    ],
    "housing.listing_search": [
        "references/intent-housing-listing-search.md",
        "references/table-app-area-dimension.md",
        "references/table-app-area-rental-listing-snapshot.md",
    ],
    "neighborhood.crime_query": [
        "references/intent-neighborhood-crime.md",
        "references/table-app-area-dimension.md",
        "references/table-v-area-metrics-latest.md",
        "references/table-app-crime-incident-snapshot.md",
    ],
    "area.metrics_query": [
        "references/intent-area-metrics.md",
        "references/table-app-area-dimension.md",
        "references/table-v-area-metrics-latest.md",
    ],
}


def load_skill_prompt(task_type: str) -> str:
    try:
        task_references = TASK_REFERENCE_MAP[task_type]
    except KeyError as exc:
        raise ValueError(f"unsupported nl-to-sql task_type: {task_type}") from exc

    root = Path(settings.skill_root)
    if not root.exists():
        local_root = Path.cwd() / "skills" / "nyc-nl-to-sql"
        if local_root.exists():
            root = local_root
    paths = ["SKILL.md", *COMMON_REFERENCES, *task_references]
    return "\n\n".join((root / path).read_text(encoding="utf-8") for path in paths)
