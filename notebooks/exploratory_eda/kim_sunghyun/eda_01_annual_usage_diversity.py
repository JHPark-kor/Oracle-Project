"""EDA 01: annual card use, utilization, and category diversity trends."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from _common import (
    AGE_COLUMNS,
    CATEGORIES,
    add_source_footer,
    concentration_metrics,
    configure_korean_font,
    ensure_output_dirs,
    require_columns,
    save_figure_with_source_metadata,
    save_table,
)


ANNUAL_TABLE_NAME = "kim_sunghyun_annual_card_issuance_usage_utilization_metrics.csv"
DIVERSITY_TABLE_NAME = "kim_sunghyun_annual_category_concentration_diversity_metrics.csv"
FIGURE_NAME = "kim_sunghyun_01_annual_card_usage_and_category_diversity_trends.png"
DIRECT_CULTURE_CATEGORIES = ("공연", "전시", "문화체험")

ANNUAL_OUTPUT_COLUMNS = [
    "year",
    "issued_cards",
    "users",
    "user_rate_pct",
    "issued_amount_won",
    "used_amount_won",
    "issued_utilization_pct",
    "transactions_per_issued",
    "senior_60_plus_share_pct",
]


def build_annual_usage_table(usage: pd.DataFrame) -> pd.DataFrame:
    """Aggregate district records into the five annual Seoul totals."""

    sum_columns = [
        "budget_won",
        "issued_cards",
        "users",
        "issued_male",
        "issued_female",
        "issued_amount_won",
        *AGE_COLUMNS,
        "used_amount_won",
        "used_amount_male_won",
        "used_amount_female_won",
        "transactions",
        *[f"amount_{category}" for category in CATEGORIES],
        *[f"count_{category}" for category in CATEGORIES],
    ]
    require_columns(usage, ["year", *sum_columns], context="EDA 01 이용실적")

    yearly = usage.groupby("year", as_index=False)[sum_columns].sum()
    yearly["user_rate_pct"] = yearly["users"] / yearly["issued_cards"] * 100
    yearly["budget_utilization_pct"] = (
        yearly["used_amount_won"] / yearly["budget_won"] * 100
    )
    yearly["issued_utilization_pct"] = (
        yearly["used_amount_won"] / yearly["issued_amount_won"] * 100
    )
    yearly["used_per_issued_won"] = (
        yearly["used_amount_won"] / yearly["issued_cards"]
    )
    yearly["used_per_user_won"] = yearly["used_amount_won"] / yearly["users"]
    yearly["transactions_per_issued"] = (
        yearly["transactions"] / yearly["issued_cards"]
    )
    yearly["average_transaction_won"] = (
        yearly["used_amount_won"] / yearly["transactions"]
    )
    yearly["female_issued_share_pct"] = (
        yearly["issued_female"] / yearly["issued_cards"] * 100
    )
    senior_columns = [
        "issued_60s",
        "issued_70s",
        "issued_80s",
        "issued_90s",
        "issued_100_plus",
    ]
    yearly["senior_60_plus_share_pct"] = (
        yearly[senior_columns].sum(axis=1) / yearly["issued_cards"] * 100
    )
    return yearly


def build_annual_category_diversity_table(usage: pd.DataFrame) -> pd.DataFrame:
    """Calculate annual CR3, HHI, Shannon, and direct-culture share."""

    required = [
        "year",
        *[f"amount_{category}" for category in CATEGORIES],
    ]
    require_columns(usage, required, context="EDA 01 분야별 이용실적")

    metrics: list[dict[str, object]] = []
    for year, group in usage.groupby("year"):
        amounts = np.array(
            [group[f"amount_{category}"].sum() for category in CATEGORIES],
            dtype=float,
        )
        amount_total = amounts.sum()
        cr3, hhi, shannon = concentration_metrics(amounts)
        direct_culture_amount = sum(
            group[f"amount_{category}"].sum()
            for category in DIRECT_CULTURE_CATEGORIES
        )
        metrics.append(
            {
                "year": year,
                "cr3_amount_pct": cr3,
                "hhi_amount": hhi,
                "shannon_amount": shannon,
                "direct_culture_amount_share_pct": (
                    direct_culture_amount / amount_total * 100
                ),
            }
        )
    return pd.DataFrame(metrics)


def _direct_culture_transaction_shares(yearly: pd.DataFrame) -> list[float]:
    """Return annual direct-culture transaction shares for Figure 1."""

    shares: list[float] = []
    for _, row in yearly.iterrows():
        direct_count = sum(
            row[f"count_{category}"] for category in DIRECT_CULTURE_CATEGORIES
        )
        shares.append(direct_count / row["transactions"] * 100)
    return shares


def plot_annual_usage_diversity(
    yearly: pd.DataFrame,
    diversity: pd.DataFrame,
    save_path: Path | None = None,
):
    """Draw the four-panel annual use and diversity summary."""

    import matplotlib.pyplot as plt

    configure_korean_font()
    direct_transactions = _direct_culture_transaction_shares(yearly)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    years = yearly["year"]

    axes[0, 0].plot(years, yearly["issued_cards"], marker="o", label="발급매수")
    axes[0, 0].plot(years, yearly["users"], marker="o", label="1회 이상 이용자")
    axes[0, 0].set_title("발급 및 실제 이용 규모")
    axes[0, 0].set_ylabel("명·매")
    axes[0, 0].legend()

    axes[0, 1].plot(
        years,
        yearly["user_rate_pct"],
        marker="o",
        color="#2563eb",
        label="발급자 중 이용자 비율",
    )
    axes[0, 1].plot(
        years,
        yearly["issued_utilization_pct"],
        marker="o",
        color="#ea580c",
        label="발급금액 소진율",
    )
    axes[0, 1].set_title("이용 참여와 금액 소진")
    axes[0, 1].set_ylabel("%")
    axes[0, 1].legend()

    axes[1, 0].plot(
        diversity["year"],
        diversity["cr3_amount_pct"],
        marker="o",
        color="#7c3aed",
        label="상위 3개 분야 집중도(CR3)",
    )
    axes[1, 0].set_title("이용 분야 집중도")
    axes[1, 0].set_ylabel("%")
    axes[1, 0].legend()

    axes[1, 1].plot(
        diversity["year"],
        diversity["direct_culture_amount_share_pct"],
        marker="o",
        color="#059669",
        label="공연·전시·문화체험 금액 비중",
    )
    axes[1, 1].plot(
        years,
        direct_transactions,
        marker="o",
        color="#0f766e",
        linestyle="--",
        label="공연·전시·문화체험 건수 비중",
    )
    axes[1, 1].set_title("직접 문화경험 분야 비중")
    axes[1, 1].set_ylabel("%")
    axes[1, 1].legend()

    for axis in axes.flat:
        axis.set_xticks(years)
        axis.grid(alpha=0.2)
    fig.suptitle("핵심 1. 서울시 문화누리카드 5개년 이용·다양성 변화", fontsize=16)
    add_source_footer(fig, include_merchants=False)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    if save_path:
        save_figure_with_source_metadata(
            fig,
            save_path,
            include_merchants=False,
        )
    return fig


def run_analysis(
    usage: pd.DataFrame,
    output_dir: str | Path,
    *,
    create_plot: bool = True,
) -> dict[str, object]:
    """Build and save EDA 01 tables and its corresponding figure."""

    import matplotlib.pyplot as plt

    table_dir, figure_dir = ensure_output_dirs(output_dir)
    yearly = build_annual_usage_table(usage)
    diversity = build_annual_category_diversity_table(usage)

    annual_path = save_table(yearly[ANNUAL_OUTPUT_COLUMNS], table_dir / ANNUAL_TABLE_NAME)
    diversity_path = save_table(diversity, table_dir / DIVERSITY_TABLE_NAME)
    paths: dict[str, Path] = {
        "annual_card_issuance_usage_utilization_metrics": annual_path,
        "annual_category_concentration_diversity_metrics": diversity_path,
    }
    if create_plot:
        figure_path = figure_dir / FIGURE_NAME
        figure = plot_annual_usage_diversity(yearly, diversity, figure_path)
        plt.close(figure)
        paths["01_annual_card_usage_and_category_diversity_trends"] = figure_path
    return {"yearly": yearly, "diversity": diversity, "paths": paths}
