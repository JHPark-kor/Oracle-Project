"""EDA 02: five-year district utilization and current-supply screening."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from _common import (
    ANALYSIS_YEARS,
    SEOUL_DISTRICTS,
    add_source_footer,
    configure_korean_font,
    ensure_output_dirs,
    require_columns,
    save_figure_with_source_metadata,
    save_table,
)


TABLE_NAME = "district_five_year_utilization_supply_diagnostic.csv"
FIGURE_NAME = "02_district_five_year_utilization_supply_diagnostic.png"

LABELED_REVIEW_TYPES = {
    "지속 저이용·저공급 검토",
    "지속 저이용 검토",
    "악화·저공급 검토",
    "공급·이용 동시 검토",
}

DIAGNOSTIC_OUTPUT_COLUMNS = [
    "district",
    "preliminary_type",
    "mean_utilization_2021_2025",
    "utilization_slope_pp_per_year",
    "utilization_std_pp",
    "delta_2021_2025_pp",
    "bottom_quartile_year_count",
    "issued_utilization_pct",
    "user_rate_pct",
    "transactions_per_issued",
    "culture_experience_transaction_pct",
    "cr3_amount_pct",
    "shannon_amount",
    "merchants_per_1000_issued",
    "merchant_shannon",
    "strongest_mismatch_category",
    "strongest_mismatch_z",
    "analysis_note",
    "final_limit",
]


def build_district_trend_metrics(usage: pd.DataFrame) -> pd.DataFrame:
    """Calculate each district's five-year level, trend, and volatility."""

    require_columns(
        usage,
        ["district", "year", "issued_utilization_pct"],
        context="EDA 02 이용실적",
    )
    pivot = usage.pivot(
        index="district",
        columns="year",
        values="issued_utilization_pct",
    ).reindex(index=SEOUL_DISTRICTS, columns=ANALYSIS_YEARS)
    if pivot.isna().any().any():
        missing = pivot.isna().stack().loc[lambda value: value].index.tolist()
        raise ValueError(f"자치구·연도 이용률이 누락되었습니다: {missing[:5]}")

    years = np.asarray(ANALYSIS_YEARS, dtype=float)
    centered_years = years - years.mean()
    yearly_q25 = pivot.quantile(0.25, axis=0)
    rank_latest = pivot[ANALYSIS_YEARS[-1]].rank(method="min", ascending=False).astype(int)
    rows: list[dict[str, object]] = []
    for district, values in pivot.iterrows():
        rates = values.to_numpy(float)
        rows.append(
            {
                "district": district,
                **{f"utilization_{year}": values[year] for year in ANALYSIS_YEARS},
                "mean_utilization_2021_2025": float(rates.mean()),
                "utilization_slope_pp_per_year": float(
                    np.polyfit(centered_years, rates, 1)[0]
                ),
                "utilization_std_pp": float(rates.std(ddof=1)),
                "utilization_range_pp": float(rates.max() - rates.min()),
                "delta_2021_2025_pp": float(
                    values[ANALYSIS_YEARS[-1]] - values[ANALYSIS_YEARS[0]]
                ),
                "bottom_quartile_year_count": int(
                    sum(values[year] <= yearly_q25[year] for year in ANALYSIS_YEARS)
                ),
                "utilization_rank_2025": int(rank_latest[district]),
            }
        )
    return pd.DataFrame(rows)


def classify_district_trends(trend: pd.DataFrame) -> pd.DataFrame:
    """Add auditable relative trend flags and screening labels."""

    required = [
        "mean_utilization_2021_2025",
        "utilization_slope_pp_per_year",
        "utilization_std_pp",
        "bottom_quartile_year_count",
    ]
    require_columns(trend, required, context="EDA 02 자치구 추세")
    result = trend.copy()
    mean_q25 = result["mean_utilization_2021_2025"].quantile(0.25)
    mean_q75 = result["mean_utilization_2021_2025"].quantile(0.75)
    slope_q75 = result["utilization_slope_pp_per_year"].quantile(0.75)
    volatility_median = result["utilization_std_pp"].median()
    volatility_q75 = result["utilization_std_pp"].quantile(0.75)

    result["persistent_low_flag"] = (
        (result["mean_utilization_2021_2025"] <= mean_q25)
        & (result["bottom_quartile_year_count"] >= 3)
    )
    result["improving_flag"] = (
        result["utilization_slope_pp_per_year"] >= slope_q75
    ) & (result["utilization_slope_pp_per_year"] > 0)
    result["worsening_flag"] = result["utilization_slope_pp_per_year"] < 0
    result["stable_high_flag"] = (
        (result["mean_utilization_2021_2025"] >= mean_q75)
        & (result["utilization_std_pp"] <= volatility_median)
    )
    result["volatile_flag"] = result["utilization_std_pp"] >= volatility_q75
    result["trend_type"] = np.select(
        [
            result["persistent_low_flag"],
            result["worsening_flag"],
            result["improving_flag"],
            result["stable_high_flag"],
            result["volatile_flag"],
        ],
        ["지속 저이용 후보", "악화형", "개선형", "안정 우수형", "변동형"],
        default="중간형",
    )
    result["classification_note"] = (
        "5개년 이용률 수준·선형 추세·변동성의 자치구 내 상대 분류; "
        "대상자·접근성 결합 전 예비 진단"
    )
    return result.sort_values(
        ["persistent_low_flag", "mean_utilization_2021_2025"],
        ascending=[False, True],
    ).reset_index(drop=True)


def build_district_trend_stability(usage: pd.DataFrame) -> pd.DataFrame:
    """Build the complete five-year trend screening table."""

    return classify_district_trends(build_district_trend_metrics(usage))


def _strongest_category_mismatch(
    category_supply_usage: pd.DataFrame,
) -> pd.DataFrame:
    """Select each district's strongest positive category mismatch."""

    require_columns(
        category_supply_usage,
        ["district", "category_mid", "supply_use_mismatch_z", "mismatch_type"],
        context="EDA 02 분야별 불일치",
    )
    strongest_index = category_supply_usage.groupby("district")[
        "supply_use_mismatch_z"
    ].idxmax()
    return category_supply_usage.loc[
        strongest_index,
        ["district", "category_mid", "supply_use_mismatch_z", "mismatch_type"],
    ].rename(
        columns={
            "category_mid": "strongest_mismatch_category",
            "supply_use_mismatch_z": "strongest_mismatch_z",
            "mismatch_type": "strongest_mismatch_type",
        }
    )


def classify_district_diagnostic_type(diagnostic: pd.DataFrame) -> pd.DataFrame:
    """Classify districts into policy-review types without claiming causality."""

    result = diagnostic.copy()
    low_supply = result["supply_level"].eq("공급 낮음")
    low_usage = result["usage_level"].eq("이용 낮음")
    result["preliminary_type"] = np.select(
        [
            result["persistent_low_flag"] & low_supply,
            result["persistent_low_flag"],
            result["worsening_flag"] & low_supply,
            low_supply & low_usage,
            (~low_supply) & low_usage,
            low_supply & (~low_usage),
            result["improving_flag"],
        ],
        [
            "지속 저이용·저공급 검토",
            "지속 저이용 검토",
            "악화·저공급 검토",
            "공급·이용 동시 검토",
            "비공급 장벽 검토",
            "역외이용·핵심가맹점 검토",
            "개선형",
        ],
        default="일반 모니터링",
    )
    result["analysis_note"] = np.select(
        [
            result["preliminary_type"].eq("지속 저이용·저공급 검토"),
            result["preliminary_type"].eq("지속 저이용 검토"),
            result["preliminary_type"].eq("악화·저공급 검토"),
            result["preliminary_type"].eq("공급·이용 동시 검토"),
            result["preliminary_type"].eq("비공급 장벽 검토"),
            result["preliminary_type"].eq("역외이용·핵심가맹점 검토"),
            result["preliminary_type"].eq("개선형"),
        ],
        [
            "5개년 저이용 지속성과 현재 저공급이 겹침; 수요·거리 자료 우선 결합",
            "공급량 외 정보·가격·이동·선호 장벽 확인",
            "이용률 하락과 현재 저공급이 겹침; 연도별 가맹점 이력 확인",
            "최근 이용과 현재 공급 모두 중앙값 미만; 행정동 상세 진단",
            "현재 공급은 상대적으로 높음; 정보·가격·분야 정합성 점검",
            "현재 공급이 낮아도 이용은 높음; 역외·온라인·핵심가맹점 효과 확인",
            "이용률 상승 원인과 유지 가능성 확인",
        ],
        default="현재 지표에서 뚜렷한 단일 취약 신호 없음",
    )
    result["final_limit"] = (
        "상대적 예비 분류이며 문화누리 대상자 수·행정동 접근성 결합 전 확정 금지"
    )
    return result


def build_district_diagnostic_table(
    trend: pd.DataFrame,
    usage_supply: pd.DataFrame,
    category_supply_usage: pd.DataFrame,
) -> pd.DataFrame:
    """Build the one-row-per-district screening table for team handoff."""

    strongest = _strongest_category_mismatch(category_supply_usage)
    current_columns = [
        "district",
        "issued_cards",
        "user_rate_pct",
        "issued_utilization_pct",
        "transactions_per_issued",
        "culture_experience_transaction_pct",
        "cr3_amount_pct",
        "shannon_amount",
        "senior_60_plus_share_pct",
        "merchant_count",
        "merchants_per_1000_issued",
        "merchant_shannon",
        "phone_payment_count",
        "visiting_service_count",
        "disabled_friendly_count",
        "supply_level",
        "usage_level",
        "supply_usage_type",
    ]
    require_columns(usage_supply, current_columns, context="EDA 02 이용–공급 자료")
    diagnostic = trend.merge(
        usage_supply[current_columns],
        on="district",
        validate="1:1",
    ).merge(strongest, on="district", validate="1:1")
    diagnostic = classify_district_diagnostic_type(diagnostic)
    return diagnostic.sort_values(
        ["persistent_low_flag", "mean_utilization_2021_2025"],
        ascending=[False, True],
    ).reset_index(drop=True)


def plot_district_diagnostic(
    diagnostic: pd.DataFrame,
    save_path: Path | None = None,
):
    """Plot all districts while labeling only the documented review groups."""

    import matplotlib.pyplot as plt

    configure_korean_font()
    type_colors = {
        "지속 저이용·저공급 검토": "#b91c1c",
        "지속 저이용 검토": "#ef4444",
        "악화·저공급 검토": "#f97316",
        "공급·이용 동시 검토": "#f59e0b",
        "비공급 장벽 검토": "#7c3aed",
        "역외이용·핵심가맹점 검토": "#2563eb",
        "개선형": "#059669",
        "일반 모니터링": "#94a3b8",
    }
    fig, axis = plt.subplots(figsize=(12, 8))
    for preliminary_type, group in diagnostic.groupby("preliminary_type"):
        axis.scatter(
            group["mean_utilization_2021_2025"],
            group["utilization_slope_pp_per_year"],
            s=62,
            alpha=0.85,
            color=type_colors.get(preliminary_type, "#94a3b8"),
            label=preliminary_type,
        )

    labeled = diagnostic.loc[
        diagnostic["preliminary_type"].isin(LABELED_REVIEW_TYPES)
    ]
    for _, row in labeled.iterrows():
        axis.annotate(
            row["district"],
            (
                row["mean_utilization_2021_2025"],
                row["utilization_slope_pp_per_year"],
            ),
            xytext=(4, 3),
            textcoords="offset points",
            fontsize=8,
        )

    axis.axhline(0, color="#475569", linewidth=1, linestyle="--")
    axis.axvline(
        diagnostic["mean_utilization_2021_2025"].median(),
        color="#94a3b8",
        linewidth=1,
        linestyle="--",
    )
    axis.set_title("핵심 2. 자치구별 5개년 이용 수준·추세와 현재 공급 예비 진단")
    axis.set_xlabel("2021–2025년 평균 발급금액 대비 이용률(%)")
    axis.set_ylabel("연평균 이용률 변화 기울기(%p/년)")
    axis.legend(title="예비 진단", bbox_to_anchor=(1.02, 1), loc="upper left")
    axis.grid(alpha=0.2)
    fig.text(
        0.5,
        0.055,
        "※ 정책 우선 검토 유형에 해당하는 자치구만 명칭 표시",
        ha="center",
        fontsize=8,
        color="#475569",
    )
    fig.text(
        0.5,
        0.035,
        "대상자 수·행정동 거리 결합 전 상대적 검토 유형이며 최종 취약지역 판정이 아님",
        ha="center",
        fontsize=9,
        color="#b91c1c",
    )
    add_source_footer(fig, include_merchants=True)
    fig.tight_layout(rect=(0, 0.085, 1, 1))
    if save_path:
        save_figure_with_source_metadata(
            fig,
            save_path,
            include_merchants=True,
        )
    return fig


def run_analysis(
    usage: pd.DataFrame,
    usage_supply: pd.DataFrame,
    category_supply_usage: pd.DataFrame,
    output_dir: str | Path,
    *,
    create_plot: bool = True,
) -> dict[str, object]:
    """Build and save EDA 02's diagnostic table and figure."""

    import matplotlib.pyplot as plt

    table_dir, figure_dir = ensure_output_dirs(output_dir)
    trend = build_district_trend_stability(usage)
    diagnostic = build_district_diagnostic_table(
        trend,
        usage_supply,
        category_supply_usage,
    )
    table_path = save_table(
        diagnostic[DIAGNOSTIC_OUTPUT_COLUMNS],
        table_dir / TABLE_NAME,
    )
    paths: dict[str, Path] = {
        "district_five_year_utilization_supply_diagnostic": table_path
    }
    if create_plot:
        figure_path = figure_dir / FIGURE_NAME
        figure = plot_district_diagnostic(diagnostic, figure_path)
        plt.close(figure)
        paths["02_district_five_year_utilization_supply_diagnostic"] = figure_path
    return {"trend": trend, "diagnostic": diagnostic, "paths": paths}
