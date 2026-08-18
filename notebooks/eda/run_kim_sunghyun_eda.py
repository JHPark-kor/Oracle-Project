"""Run all four Kim Sunghyun Culture Nuri Card EDA analyses."""

from __future__ import annotations

import sys
from pathlib import Path

from _common import (
    build_merchant_supply,
    build_usage_supply_relationship,
    default_paths,
    find_project_root,
    load_merchant_data,
    load_usage_data,
)
from eda_01_annual_usage_diversity import run_analysis as run_annual_analysis
from eda_02_district_usage_supply_diagnostic import (
    run_analysis as run_district_analysis,
)
from eda_03_category_usage_supply_gap import (
    build_category_supply_usage,
    run_analysis as run_category_analysis,
)
from eda_04_supply_utilization_sensitivity import (
    DEFAULT_PERMUTATIONS,
    run_analysis as run_sensitivity_analysis,
)


def run_pipeline(
    project_root: Path | None = None,
    *,
    create_plots: bool = True,
    permutations: int = DEFAULT_PERMUTATIONS,
) -> dict[str, object]:
    """Load each source once and run EDA 01 through EDA 04."""

    root = project_root or find_project_root(Path(__file__).resolve().parent)
    paths = default_paths(root)

    usage, usage_quality = load_usage_data(paths["usage_file"])
    failed_quality = usage_quality.loc[~usage_quality["passed"]]
    if not failed_quality.empty:
        failed_checks = ", ".join(failed_quality["check"].astype(str).unique())
        raise ValueError(
            "이용실적 품질 점검 실패로 EDA를 중단합니다: " f"{failed_checks}"
        )

    _, merchants, merchant_quality = load_merchant_data(paths["merchant_file"])
    merchant_supply = build_merchant_supply(merchants)
    usage_supply = build_usage_supply_relationship(usage, merchant_supply)

    annual = run_annual_analysis(
        usage,
        paths["output_dir"],
        create_plot=create_plots,
    )

    # EDA 02 and 03 both use the same category-matched dataset. Build it once.
    category_supply_usage = build_category_supply_usage(usage, merchants)
    district = run_district_analysis(
        usage,
        usage_supply,
        category_supply_usage,
        paths["output_dir"],
        create_plot=create_plots,
    )
    category = run_category_analysis(
        usage,
        merchants,
        paths["output_dir"],
        category_supply_usage=category_supply_usage,
        create_plot=create_plots,
    )
    sensitivity = run_sensitivity_analysis(
        usage_supply,
        paths["output_dir"],
        permutations=permutations,
        create_plot=create_plots,
    )

    output_paths: dict[str, Path] = {}
    for analysis in (annual, district, category, sensitivity):
        output_paths.update(analysis["paths"])

    return {
        "quality": usage_quality,
        "merchant_quality": merchant_quality,
        "yearly": annual["yearly"],
        "concentration": annual["diversity"],
        "diagnostic": district["diagnostic"],
        "category_supply_usage": category["category_supply_usage"],
        "category_priority": category["candidates"],
        "sensitivity": sensitivity["sensitivity"],
        "paths": output_paths,
    }


def _print_completion_summary(result: dict[str, object]) -> None:
    """Print a compact, human-readable completion summary."""

    output_paths = result["paths"]
    table_count = sum(Path(path).suffix == ".csv" for path in output_paths.values())
    figure_count = sum(Path(path).suffix == ".png" for path in output_paths.values())
    print("[완료] 김성현 문화누리카드 EDA 01~04")
    print(f"- 이용실적 품질검사 실패: {int((~result['quality']['passed']).sum())}건")
    print(f"- 생성 표: {table_count}개")
    print(f"- 생성 이미지: {figure_count}개")
    print("- 산출물:")
    for name, path in output_paths.items():
        print(f"  {name}: {path}")


def main() -> None:
    """CLI entry point with an explicit failure message and non-zero exit."""

    try:
        result = run_pipeline()
    except Exception as error:
        print(f"[실패] 김성현 EDA 실행 중 오류가 발생했습니다: {error}", file=sys.stderr)
        raise
    _print_completion_summary(result)


if __name__ == "__main__":
    main()
