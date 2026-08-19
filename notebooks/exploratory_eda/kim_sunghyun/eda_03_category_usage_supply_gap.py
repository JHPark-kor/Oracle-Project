"""EDA 03: district-category usage and current-supply mismatch screening."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from _common import (
    MERCHANT_USAGE_CATEGORY_MAP,
    SUPPLY_SNAPSHOT,
    USAGE_YEAR,
    add_source_footer,
    configure_korean_font,
    ensure_output_dirs,
    require_columns,
    save_figure_with_source_metadata,
    save_table,
    standardize,
)


TABLE_NAME = "category_usage_supply_gap_candidates.csv"
FIGURE_NAME = "03_category_usage_supply_gap_heatmap.png"
MISMATCH_THRESHOLD = 1.0
TOP_CANDIDATES_PER_CATEGORY = 3


def build_category_supply_intensity(merchants: pd.DataFrame) -> pd.Series:
    """Count current merchants by district and matched mid-level category."""

    require_columns(
        merchants,
        ["district", "category_mid"],
        context="EDA 03 가맹점",
    )
    return (
        merchants.groupby(["district", "category_mid"])
        .size()
        .rename("merchant_count")
    )


def build_category_usage_intensity(
    usage: pd.DataFrame,
    merchants: pd.DataFrame,
    usage_year: int = USAGE_YEAR,
) -> pd.DataFrame:
    """Build matched district-category use and supply intensity inputs."""

    required_usage_columns = ["year", "district", "issued_cards"]
    for usage_categories in MERCHANT_USAGE_CATEGORY_MAP.values():
        required_usage_columns.extend(f"amount_{category}" for category in usage_categories)
        required_usage_columns.extend(f"count_{category}" for category in usage_categories)
    require_columns(usage, required_usage_columns, context="EDA 03 이용실적")

    district_usage = usage.loc[usage["year"] == usage_year]
    if district_usage["district"].nunique() != 25:
        raise ValueError(f"{usage_year}년 자치구가 25개가 아닙니다.")

    merchant_counts = build_category_supply_intensity(merchants)
    rows: list[dict[str, object]] = []
    for _, district_row in district_usage.iterrows():
        district = district_row["district"]
        for merchant_category, usage_categories in MERCHANT_USAGE_CATEGORY_MAP.items():
            amount = float(
                sum(district_row[f"amount_{category}"] for category in usage_categories)
            )
            transactions = float(
                sum(district_row[f"count_{category}"] for category in usage_categories)
            )
            rows.append(
                {
                    "usage_year": usage_year,
                    "supply_snapshot": SUPPLY_SNAPSHOT,
                    "district": district,
                    "category_mid": merchant_category,
                    "usage_categories": ", ".join(usage_categories),
                    "issued_cards": float(district_row["issued_cards"]),
                    "used_amount_won": amount,
                    "transactions": transactions,
                    "merchant_count": int(
                        merchant_counts.get((district, merchant_category), 0)
                    ),
                }
            )

    matched = pd.DataFrame(rows)
    matched["amount_per_issued_won"] = (
        matched["used_amount_won"] / matched["issued_cards"]
    )
    matched["transactions_per_1000_issued"] = (
        matched["transactions"] / matched["issued_cards"] * 1000
    )
    matched["merchants_per_1000_issued"] = (
        matched["merchant_count"] / matched["issued_cards"] * 1000
    )
    matched["district_amount_share_pct"] = (
        matched["used_amount_won"]
        / matched.groupby("district")["used_amount_won"].transform("sum")
        * 100
    )
    matched["district_merchant_share_pct"] = (
        matched["merchant_count"]
        / matched.groupby("district")["merchant_count"].transform("sum")
        * 100
    )
    return matched


def calculate_usage_supply_gap(matched: pd.DataFrame) -> pd.DataFrame:
    """Standardize within category and calculate the documented mismatch score."""

    require_columns(
        matched,
        [
            "category_mid",
            "amount_per_issued_won",
            "transactions_per_1000_issued",
            "merchants_per_1000_issued",
        ],
        context="EDA 03 이용–공급 결합자료",
    )
    result = matched.copy()
    grouped = result.groupby("category_mid", group_keys=False)
    result["amount_intensity_z"] = grouped["amount_per_issued_won"].transform(
        standardize
    )
    result["transaction_intensity_z"] = grouped[
        "transactions_per_1000_issued"
    ].transform(standardize)
    result["supply_intensity_z"] = grouped[
        "merchants_per_1000_issued"
    ].transform(standardize)
    result["observed_use_signal_z"] = (
        result["amount_intensity_z"] + result["transaction_intensity_z"]
    ) / 2
    result["supply_use_mismatch_z"] = (
        result["observed_use_signal_z"] - result["supply_intensity_z"]
    )
    result["mismatch_type"] = np.select(
        [
            result["supply_use_mismatch_z"] >= 1,
            result["supply_use_mismatch_z"] <= -1,
        ],
        ["이용 강함·현재 공급 약함 후보", "현재 공급 강함·이용 약함 후보"],
        default="중간 범위",
    )
    result["interpretation_limit"] = (
        "이용자 거주지·가맹점 소재지 기준 및 역외·온라인 이용 확인 전 탐색점수"
    )
    return result.sort_values(
        ["supply_use_mismatch_z", "district", "category_mid"],
        ascending=[False, True, True],
    ).reset_index(drop=True)


def build_category_supply_usage(
    usage: pd.DataFrame,
    merchants: pd.DataFrame,
    usage_year: int = USAGE_YEAR,
) -> pd.DataFrame:
    """Build the complete district-category mismatch dataset once."""

    intensity = build_category_usage_intensity(usage, merchants, usage_year)
    return calculate_usage_supply_gap(intensity)


def select_gap_candidates(
    category_supply_usage: pd.DataFrame,
    threshold: float = MISMATCH_THRESHOLD,
    top_per_category: int = TOP_CANDIDATES_PER_CATEGORY,
) -> pd.DataFrame:
    """Keep the strongest positive mismatch screening rows per category."""

    require_columns(
        category_supply_usage,
        ["category_mid", "supply_use_mismatch_z"],
        context="EDA 03 불일치 결과",
    )
    candidates = category_supply_usage.loc[
        category_supply_usage["supply_use_mismatch_z"] >= threshold
    ].copy()
    candidates["category_priority_rank"] = candidates.groupby("category_mid")[
        "supply_use_mismatch_z"
    ].rank(method="first", ascending=False)
    candidates = candidates.loc[
        candidates["category_priority_rank"] <= top_per_category
    ]
    columns = [
        "district",
        "category_mid",
        "category_priority_rank",
        "amount_per_issued_won",
        "transactions_per_1000_issued",
        "merchants_per_1000_issued",
        "supply_use_mismatch_z",
        "mismatch_type",
        "interpretation_limit",
    ]
    return candidates[columns].sort_values(
        ["supply_use_mismatch_z", "category_mid"],
        ascending=[False, True],
    ).reset_index(drop=True)


def plot_usage_supply_gap_heatmap(
    matched: pd.DataFrame,
    save_path: Path | None = None,
):
    """Draw the district-category mismatch heatmap."""

    import matplotlib.pyplot as plt

    configure_korean_font()
    pivot = matched.pivot(
        index="category_mid",
        columns="district",
        values="supply_use_mismatch_z",
    )
    district_order = (
        matched.groupby("district")["supply_use_mismatch_z"]
        .max()
        .sort_values(ascending=False)
        .index
    )
    category_order = (
        matched.groupby("category_mid")["supply_use_mismatch_z"]
        .max()
        .sort_values(ascending=False)
        .index
    )
    pivot = pivot.reindex(index=category_order, columns=district_order)
    values = pivot.to_numpy(float)
    limit = max(1.0, float(np.nanquantile(np.abs(values), 0.97)))

    fig, axis = plt.subplots(figsize=(17, 8.5))
    image = axis.imshow(
        values,
        aspect="auto",
        cmap="RdBu_r",
        vmin=-limit,
        vmax=limit,
    )
    axis.set_xticks(range(len(pivot.columns)), pivot.columns, rotation=90)
    axis.set_yticks(range(len(pivot.index)), pivot.index)
    axis.set_title("핵심 3. 동일 분야 이용강도–현재 공급강도 불일치 탐색")
    colorbar = fig.colorbar(image, ax=axis, fraction=0.02, pad=0.015)
    colorbar.set_label("불일치 점수(z): 양수=이용 대비 현재 공급 약함 후보")
    fig.text(
        0.5,
        0.038,
        "2025 이용자 거주지·2026 공급 기준 및 역외·온라인 이용 확인 전 탐색점수",
        ha="center",
        fontsize=9,
        color="#b91c1c",
    )
    add_source_footer(fig, include_merchants=True)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    if save_path:
        save_figure_with_source_metadata(
            fig,
            save_path,
            include_merchants=True,
        )
    return fig


def run_analysis(
    usage: pd.DataFrame,
    merchants: pd.DataFrame,
    output_dir: str | Path,
    *,
    category_supply_usage: pd.DataFrame | None = None,
    create_plot: bool = True,
) -> dict[str, object]:
    """Build and save EDA 03's candidate table and heatmap."""

    import matplotlib.pyplot as plt

    table_dir, figure_dir = ensure_output_dirs(output_dir)
    matched = (
        category_supply_usage
        if category_supply_usage is not None
        else build_category_supply_usage(usage, merchants)
    )
    candidates = select_gap_candidates(matched)
    table_path = save_table(candidates, table_dir / TABLE_NAME)
    paths: dict[str, Path] = {"category_usage_supply_gap_candidates": table_path}
    if create_plot:
        figure_path = figure_dir / FIGURE_NAME
        figure = plot_usage_supply_gap_heatmap(matched, figure_path)
        plt.close(figure)
        paths["03_category_usage_supply_gap_heatmap"] = figure_path
    return {
        "category_supply_usage": matched,
        "candidates": candidates,
        "paths": paths,
    }
