"""Build 100m, dong, and district preference-demand outputs and maps."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import sklearn

from notebooks.exploratory_eda.kim_sunghyun._common import load_usage_data

from .build_mapping import find_project_root
from .external_validation import (
    ARTS_POPULATION_SCOPE,
    CARD_GEOGRAPHY_BASIS,
    CARD_GEOGRAPHY_INTERPRETATION_LIMIT,
    EXCLUDED_CARD_CATEGORIES,
    build_arts_directional_validation,
    build_card_crosswalk_sensitivity_summary,
    build_card_external_validation,
    build_validation_crosswalk_table,
)
from .interactive_maps import (
    write_interactive_dong_map,
    write_interactive_grid_map,
)
from .mapping import PREFERENCE_OUTPUT_CATEGORIES
from .spatial_demand import (
    OTHER_DEMAND_COLUMN,
    POTENTIAL_DEMAND_COLUMN,
    TARGET_POPULATION_COLUMN,
    build_all_spatial_demand,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument(
        "--skip-maps",
        action="store_true",
        help="계산 CSV만 만들고 대용량 HTML 지도 생성을 건너뜁니다.",
    )
    parser.add_argument(
        "--skip-external-validation",
        action="store_true",
        help="2024년 카드 이용실적 외적 타당성 비교를 건너뜁니다.",
    )
    return parser


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = build_parser().parse_args()
    root = (args.project_root or find_project_root()).resolve()
    population_path = (
        root
        / "data/processed/preference_analysis/population/"
        "grid_sex_age_target_population_model_input_2024.csv"
    )
    probability_path = (
        root
        / "data/processed/preference_analysis/model/"
        "sex_age_middle_category_preference_2024.csv"
    )
    grid_lookup_path = root / "data/raw/spatial/grid_pop_access.csv"
    boundary_path = root / "data/raw/spatial/boundary/seoul_admin_dong_2025.geojson"
    usage_path = (
        root / "data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx"
    )
    arts_path = root / "data/raw/surveys/arts_2021_2025.csv"
    required_inputs = [
        population_path,
        probability_path,
        grid_lookup_path,
        boundary_path,
    ]
    if not args.skip_external_validation:
        required_inputs.extend([usage_path, arts_path])
    missing = [str(path) for path in required_inputs if not path.exists()]
    if missing:
        raise FileNotFoundError(f"공간 선호분석 입력파일이 없습니다: {missing}")

    output_dir = root / "data/processed/preference_analysis/spatial"
    map_dir = output_dir / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    population = pd.read_csv(
        population_path, encoding="utf-8-sig", low_memory=False
    )
    probability = pd.read_csv(probability_path, encoding="utf-8-sig")
    grid_lookup = pd.read_csv(
        grid_lookup_path, encoding="utf-8-sig", low_memory=False
    )
    grid, dong, gu, validation = build_all_spatial_demand(
        population, probability, grid_lookup, reference_year=2024
    )

    grid_path = output_dir / "grid_middle_category_preference_demand_2024.csv"
    dong_path = output_dir / "dong_middle_category_preference_demand_2024.csv"
    gu_path = output_dir / "gu_middle_category_preference_demand_2024.csv"
    validation_path = output_dir / "spatial_validation_summary_2024.csv"
    write_csv(grid, grid_path)
    write_csv(dong, dong_path)
    write_csv(gu, gu_path)
    write_csv(validation, validation_path)

    output_paths: list[Path] = [grid_path, dong_path, gu_path, validation_path]
    external_summary: dict[str, object] = {"executed": False}
    if not args.skip_external_validation:
        usage, usage_quality = load_usage_data(usage_path)
        if not usage_quality["passed"].fillna(False).all():
            failures = usage_quality.loc[~usage_quality["passed"].fillna(False)]
            raise ValueError(
                "문화누리 이용실적 원자료 품질검증 실패:\n"
                f"{failures.to_string(index=False)}"
            )
        comparison, district_summary, category_summary, summary = (
            build_card_external_validation(gu, usage, year=2024)
        )
        sensitivity_summary = build_card_crosswalk_sensitivity_summary(
            gu, usage, year=2024
        )
        crosswalk = build_validation_crosswalk_table()
        arts = pd.read_csv(arts_path, encoding="utf-8-sig", low_memory=False)
        arts_cells, arts_summary = build_arts_directional_validation(
            probability, arts, year=2024
        )
        comparison_path = output_dir / "external_validation_2024_by_gu_category.csv"
        district_path = output_dir / "external_validation_2024_by_gu.csv"
        category_path = output_dir / "external_validation_2024_by_category.csv"
        summary_path = output_dir / "external_validation_2024_summary.csv"
        sensitivity_path = (
            output_dir / "external_validation_2024_crosswalk_sensitivity.csv"
        )
        crosswalk_path = output_dir / "external_validation_card_crosswalk_v2.csv"
        usage_quality_path = output_dir / "external_validation_usage_quality.csv"
        arts_cells_path = output_dir / "external_validation_arts_2024_by_sex_age.csv"
        arts_summary_path = output_dir / "external_validation_arts_2024_summary.csv"
        for frame, path in (
            (comparison, comparison_path),
            (district_summary, district_path),
            (category_summary, category_path),
            (summary, summary_path),
            (sensitivity_summary, sensitivity_path),
            (crosswalk, crosswalk_path),
            (usage_quality, usage_quality_path),
            (arts_cells, arts_cells_path),
            (arts_summary, arts_summary_path),
        ):
            write_csv(frame, path)
            output_paths.append(path)
        external_summary = {
            "executed": True,
            "comparison_scope": (
                f"2024년 자치구별 설정된 crosswalk로 매핑된 정책 "
                f"{len(PREFERENCE_OUTPUT_CATEGORIES)}개 분야"
            ),
            "primary_usage_metric": "transaction_count",
            "amount_role": "가격 차이에 민감한 보조 민감도 지표",
            "card_geography_basis": CARD_GEOGRAPHY_BASIS,
            "card_geography_interpretation_limit": (
                CARD_GEOGRAPHY_INTERPRETATION_LIMIT
            ),
            "arts_population_scope": ARTS_POPULATION_SCOPE,
            "crosswalk_sensitivity_executed": True,
            "excluded_card_categories": list(EXCLUDED_CARD_CATEGORIES),
            "interpretation": (
                "예측 선호와 실제 카드 이용의 외적 방향성 점검이며 "
                "모델 Accuracy·오차율 또는 인과효과가 아님"
            ),
        }

    map_paths: list[Path] = []
    if not args.skip_maps:
        grid_map_path = map_dir / "grid_preference_demand_2024.html"
        dong_map_path = map_dir / "dong_preference_demand_2024.html"
        write_interactive_grid_map(
            grid,
            grid_map_path,
            seoul_boundary_path=boundary_path,
        )
        write_interactive_dong_map(dong, boundary_path, dong_map_path)
        map_paths.extend([grid_map_path, dong_map_path])
        output_paths.extend(map_paths)

    grid_base = grid.drop_duplicates("GRID_CD")
    code_paths = [
        Path(__file__).resolve(),
        root / "src/preference_analysis/spatial_demand.py",
        root / "src/preference_analysis/interactive_maps.py",
        root / "src/preference_analysis/external_validation.py",
    ]
    metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(root),
        "python_version": platform.python_version(),
        "pandas_version": pd.__version__,
        "scikit_learn_version": sklearn.__version__,
        "geopandas_version": gpd.__version__,
        "reference_year": 2024,
        "inputs": [
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in required_inputs
        ],
        "code_files": [
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in code_paths
        ],
        "code_version_note": (
            "git_commit과 함께 실제 실행 코드 SHA-256을 기록하며, "
            "미커밋·미추적 상태에서는 code_files 해시가 재현 기준임"
        ),
        "population_model_scope": "15세 이상 성별×연령별 문화누리 대상자 추정인구",
        "grid_count": int(grid["GRID_CD"].nunique()),
        "dong_count": int(dong["행정동코드"].nunique()),
        "gu_count": int(gu["자치구코드"].nunique()),
        "target_population_total_15plus": float(
            grid_base[TARGET_POPULATION_COLUMN].sum()
        ),
        "policy_potential_demand_total": float(grid[POTENTIAL_DEMAND_COLUMN].sum()),
        "other_potential_demand_total": float(grid_base[OTHER_DEMAND_COLUMN].sum()),
        "accessibility_features_used": False,
        "probability_for_potential_demand": "preference_probability_absolute",
        "conditional_share_use": (
            f"정책 {len(PREFERENCE_OUTPUT_CATEGORIES)}개 분야 상대구성 표시용; "
            "잠재수요 계산에 미사용"
        ),
        "zero_target_grid_handling": "확률은 무자료, 잠재수요는 0; 지도에서 무자료 색상",
        "boundary_note": (
            "2024 추정치를 2025-06-30 단순화 행정동 경계에 코드로 결합해 표시; "
            "격자 행정동 배정은 기존 GRID_CD 연결표를 유지"
        ),
        "external_validation": external_summary,
        "map_generation": {
            "executed": not args.skip_maps,
            "static_precomputed_html": True,
            "retraining_when_opened": False,
            "paths": [str(path.relative_to(root)) for path in map_paths],
        },
        "outputs": [
            {
                "path": str(path.relative_to(root)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in output_paths
        ],
    }
    metadata_path = output_dir / "spatial_preference_run_metadata_2024.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("spatial preference-demand outputs")
    print(f"grids: {metadata['grid_count']:,}")
    print(f"dongs: {metadata['dong_count']:,}")
    print(f"districts: {metadata['gu_count']:,}")
    print(f"target population (15+): {metadata['target_population_total_15plus']:,.3f}")
    print(validation.to_string(index=False))
    print("outputs")
    for path in [*output_paths, metadata_path]:
        print(path)


if __name__ == "__main__":
    main()
