"""Generate and validate the satisfaction-activity middle-category tables."""

from __future__ import annotations

import argparse
from pathlib import Path

from .mapping import build_activity_mapping, transform_satisfaction_ranks


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() and (candidate / "data").is_dir():
            return candidate
    raise FileNotFoundError("Oracle-Project 저장소 루트를 찾지 못했습니다.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = (args.project_root or find_project_root()).resolve()
    source = root / "data/raw/surveys/leisure_2021_2025.csv"
    output_dir = root / "data/processed/preference_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    mapping = build_activity_mapping(source)
    transformed, validation, distribution = transform_satisfaction_ranks(source, mapping)

    mapping_path = output_dir / "leisure_activity_middle_category_mapping.csv"
    transformed_path = output_dir / "satisfaction_rank_middle_category_2021_2025.csv"
    validation_path = output_dir / "mapping_validation_summary.csv"
    distribution_path = output_dir / "satisfaction_mapping_distribution.csv"

    mapping.to_csv(mapping_path, index=False, encoding="utf-8-sig")
    transformed.to_csv(transformed_path, index=False, encoding="utf-8-sig")
    validation.to_csv(validation_path, index=False, encoding="utf-8-sig")
    distribution.to_csv(distribution_path, index=False, encoding="utf-8-sig")

    print(f"mapping: {mapping_path} ({len(mapping):,} rows)")
    print(f"transformed: {transformed_path} ({len(transformed):,} rows)")
    print(f"validation: {validation_path}")
    print(f"distribution: {distribution_path}")
    print(validation.to_string(index=False))


if __name__ == "__main__":
    main()
