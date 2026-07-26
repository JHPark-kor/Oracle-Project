"""EDA 04: supply-utilization correlation and exclusion sensitivity."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from _common import (
    add_source_footer,
    configure_korean_font,
    ensure_output_dirs,
    require_columns,
    save_figure_with_source_metadata,
    save_table,
)


TABLE_NAME = "kim_sunghyun_merchant_supply_utilization_correlation_sensitivity.csv"
FIGURE_NAME = "kim_sunghyun_04_merchant_supply_utilization_correlation_sensitivity.png"
SUPPLY_METRIC = "merchants_per_1000_issued"
USAGE_METRIC = "issued_utilization_pct"
DEFAULT_PERMUTATIONS = 5_000
RANDOM_SEED = 42

SENSITIVITY_SCENARIOS = {
    "전체 25개 자치구": (),
    "종로구 제외": ("종로구",),
    "종로구·중구 제외": ("종로구", "중구"),
    "도심·강남 4개구 제외": ("종로구", "중구", "강남구", "서초구"),
}


def pearson_correlation(x: pd.Series, y: pd.Series) -> float:
    """Return the Pearson coefficient after pairwise missing-value removal."""

    pair = pd.concat([x, y], axis=1).dropna()
    return float(pair.iloc[:, 0].corr(pair.iloc[:, 1], method="pearson"))


def spearman_correlation(x: pd.Series, y: pd.Series) -> float:
    """Return the Spearman coefficient after pairwise missing-value removal."""

    pair = pd.concat([x, y], axis=1).dropna()
    return float(pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman"))


def permutation_test(
    x: pd.Series,
    y: pd.Series,
    *,
    method: str,
    permutations: int = DEFAULT_PERMUTATIONS,
    seed: int = RANDOM_SEED,
) -> tuple[float, float, int]:
    """Return a coefficient and deterministic two-sided permutation p-value."""

    if method not in {"pearson", "spearman"}:
        raise ValueError(f"지원하지 않는 상관계수 방식입니다: {method}")
    if permutations <= 0:
        raise ValueError("순열검정 반복 횟수는 1 이상이어야 합니다.")

    pair = pd.concat([x, y], axis=1).dropna()
    if method == "spearman":
        pair = pair.rank(method="average")
    x_values = pair.iloc[:, 0].to_numpy(float)
    y_values = pair.iloc[:, 1].to_numpy(float)
    x_centered = x_values - x_values.mean()
    y_centered = y_values - y_values.mean()
    denominator = np.linalg.norm(x_centered) * np.linalg.norm(y_centered)
    if denominator == 0:
        return np.nan, np.nan, len(pair)

    x_unit = x_centered / np.linalg.norm(x_centered)
    y_unit = y_centered / np.linalg.norm(y_centered)
    observed = float(np.dot(x_unit, y_unit))
    rng = np.random.default_rng(seed)
    permuted = np.empty((permutations, len(y_unit)), dtype=float)
    for index in range(permutations):
        permuted[index] = rng.permutation(y_unit)
    simulated = permuted @ x_unit
    pvalue = (np.count_nonzero(np.abs(simulated) >= abs(observed)) + 1) / (
        permutations + 1
    )
    return observed, float(pvalue), len(pair)


def calculate_correlations(
    subset: pd.DataFrame,
    *,
    scenario: str,
    excluded: tuple[str, ...],
    permutations: int,
) -> list[dict[str, object]]:
    """Calculate both correlation methods for one exclusion scenario."""

    rows: list[dict[str, object]] = []
    for method in ("pearson", "spearman"):
        coefficient, pvalue, sample_size = permutation_test(
            subset[SUPPLY_METRIC],
            subset[USAGE_METRIC],
            method=method,
            permutations=permutations,
            seed=RANDOM_SEED,
        )
        direct_coefficient = (
            pearson_correlation(subset[SUPPLY_METRIC], subset[USAGE_METRIC])
            if method == "pearson"
            else spearman_correlation(subset[SUPPLY_METRIC], subset[USAGE_METRIC])
        )
        if not np.isclose(coefficient, direct_coefficient, atol=1e-12):
            raise ValueError(f"{scenario} {method} 상관계수 검산에 실패했습니다.")
        rows.append(
            {
                "scenario": scenario,
                "excluded_districts": ", ".join(excluded) or "없음",
                "supply_metric": SUPPLY_METRIC,
                "usage_metric": USAGE_METRIC,
                "method": method,
                "coefficient": coefficient,
                "permutation_pvalue": pvalue,
                "sample_size": sample_size,
                "permutations": permutations,
            }
        )
    return rows


def build_sensitivity_table(
    usage_supply: pd.DataFrame,
    permutations: int = DEFAULT_PERMUTATIONS,
) -> pd.DataFrame:
    """Test whether the observed supply-use relation depends on central districts."""

    require_columns(
        usage_supply,
        ["district", SUPPLY_METRIC, USAGE_METRIC],
        context="EDA 04 이용–공급 자료",
    )
    rows: list[dict[str, object]] = []
    for scenario, excluded in SENSITIVITY_SCENARIOS.items():
        subset = usage_supply.loc[~usage_supply["district"].isin(excluded)]
        rows.extend(
            calculate_correlations(
                subset,
                scenario=scenario,
                excluded=excluded,
                permutations=permutations,
            )
        )
    return pd.DataFrame(rows)


def plot_correlation_sensitivity(
    sensitivity: pd.DataFrame,
    save_path: Path | None = None,
):
    """Plot Pearson and Spearman estimates across exclusion scenarios."""

    import matplotlib.pyplot as plt

    configure_korean_font()
    selected = sensitivity.loc[sensitivity["supply_metric"].eq(SUPPLY_METRIC)].copy()
    scenario_order = selected["scenario"].drop_duplicates().tolist()
    fig, axis = plt.subplots(figsize=(11, 6.5))
    for method, color, marker in (
        ("pearson", "#ea580c", "o"),
        ("spearman", "#2563eb", "s"),
    ):
        group = selected.loc[selected["method"].eq(method)].set_index("scenario")
        group = group.reindex(scenario_order)
        axis.plot(
            scenario_order,
            group["coefficient"],
            marker=marker,
            color=color,
            linewidth=2,
            label=method.title(),
        )
        for position, value in enumerate(group["coefficient"]):
            axis.text(position, value + 0.025, f"{value:.3f}", ha="center", fontsize=8)
    axis.axhline(0, color="#475569", linewidth=1, linestyle="--")
    axis.set_ylim(-0.45, 0.45)
    axis.set_ylabel("상관계수")
    axis.set_title("핵심 4. 중심지역 제외에 따른 공급–이용 상관 민감도")
    axis.tick_params(axis="x", rotation=12)
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    fig.text(
        0.5,
        0.038,
        "발급자 1천 명당 현재 가맹점 수 vs 2025 이용률 · 인과관계 검정이 아님",
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
    usage_supply: pd.DataFrame,
    output_dir: str | Path,
    *,
    permutations: int = DEFAULT_PERMUTATIONS,
    create_plot: bool = True,
) -> dict[str, object]:
    """Build and save EDA 04's sensitivity table and figure."""

    import matplotlib.pyplot as plt

    table_dir, figure_dir = ensure_output_dirs(output_dir)
    sensitivity = build_sensitivity_table(usage_supply, permutations)
    table_path = save_table(sensitivity, table_dir / TABLE_NAME)
    paths: dict[str, Path] = {
        "merchant_supply_utilization_correlation_sensitivity": table_path
    }
    if create_plot:
        figure_path = figure_dir / FIGURE_NAME
        figure = plot_correlation_sensitivity(sensitivity, figure_path)
        plt.close(figure)
        paths["04_merchant_supply_utilization_correlation_sensitivity"] = figure_path
    return {"sensitivity": sensitivity, "paths": paths}
