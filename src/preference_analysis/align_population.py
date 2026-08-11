"""Build preference-model-aligned 100m grid sex-age population tables."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .build_mapping import find_project_root
from .population_alignment import (
    align_grid_sex_age_population,
    validate_preference_probability_cells,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--probability-input", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = build_parser().parse_args()
    root = (args.project_root or find_project_root()).resolve()
    input_path = args.input or (
        root
        / "analysis_table/data/output/서울시_격자_100m_문화누리대상자_성연령별_인구수.csv"
    )
    probability_path = args.probability_input or (
        root
        / "data/processed/preference_analysis/model/sex_age_middle_category_preference_2024.csv"
    )
    output_dir = args.output_dir or (
        root / "data/processed/preference_analysis/population"
    )

    if not input_path.exists():
        raise FileNotFoundError(f"격자 성·연령 대상자 자료가 없습니다: {input_path}")
    if not probability_path.exists():
        raise FileNotFoundError(f"성별×연령 선호확률 자료가 없습니다: {probability_path}")

    source = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False)
    probabilities = pd.read_csv(
        probability_path, encoding="utf-8-sig", low_memory=False
    )
    validate_preference_probability_cells(probabilities)
    aligned, model_input, summary, validation = align_grid_sex_age_population(
        source
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "aligned": output_dir / "grid_sex_age_target_population_aligned_2024.csv",
        "model_input": output_dir
        / "grid_sex_age_target_population_model_input_2024.csv",
        "summary": output_dir / "grid_sex_age_alignment_summary_2024.csv",
        "validation": output_dir / "grid_sex_age_alignment_validation_2024.csv",
    }
    write_csv(aligned, output_paths["aligned"])
    write_csv(model_input, output_paths["model_input"])
    write_csv(summary, output_paths["summary"])
    write_csv(validation, output_paths["validation"])

    print("성별·연령 구간 통일 완료")
    print(summary.to_string(index=False))
    print("\n검증 결과")
    print(validation.to_string(index=False))
    print("\n산출물")
    for label, path in output_paths.items():
        print(f"{label}: {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
