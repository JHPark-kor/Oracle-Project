"""Apply sex-age preference probabilities to 100m MNC target populations.

This module deliberately excludes merchant supply, distance, travel time, and
all other accessibility variables.  It converts approved absolute preference
probabilities into estimated potential demand and conserves the target
population from grid to administrative-dong and district aggregates.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from .mapping import MODEL_CATEGORIES, OTHER_CATEGORY, PREFERENCE_OUTPUT_CATEGORIES


REFERENCE_YEAR = 2024
TARGET_POPULATION_COLUMN = "target_population_est"
ABSOLUTE_PROBABILITY_COLUMN = "preference_probability_absolute"
CONDITIONAL_SHARE_COLUMN = "preference_share_conditional_mnc"
POTENTIAL_DEMAND_COLUMN = "potential_demand_absolute"
OTHER_PROBABILITY_COLUMN = "other_probability_absolute"
OTHER_DEMAND_COLUMN = "other_potential_demand"

POPULATION_KEY = ("GRID_CD", "sex_code", "model_age_code")
PROBABILITY_KEY = ("sex_code", "age_code", "middle_category")
GRID_LOOKUP_COLUMNS = (
    "GRID_CD",
    "행정동코드",
    "시군구",
    "행정동",
    "중심점_x",
    "중심점_y",
)


def _require_columns(
    frame: pd.DataFrame,
    required: Iterable[str],
    *,
    context: str,
) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{context}에 필요한 열이 없습니다: {missing}")


def _require_unique(
    frame: pd.DataFrame,
    key: Iterable[str],
    *,
    context: str,
) -> None:
    key_columns = list(key)
    duplicate_count = int(frame.duplicated(key_columns).sum())
    if duplicate_count:
        raise ValueError(
            f"{context}의 키 {key_columns}가 고유하지 않습니다: "
            f"{duplicate_count:,}행"
        )


def _as_numeric_finite(
    values: pd.Series,
    *,
    context: str,
    nonnegative: bool = False,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError(f"{context}에 결측 또는 무한대가 있습니다.")
    if nonnegative and (numeric < 0).any():
        raise ValueError(f"{context}에 음수가 있습니다.")
    return numeric


def validate_probability_input(probability: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize the 2×7×10 sex-age probability lookup."""

    probability = probability.copy()
    _require_columns(
        probability,
        PROBABILITY_KEY,
        context="성별×연령별 선호확률",
    )
    probability_column = (
        ABSOLUTE_PROBABILITY_COLUMN
        if ABSOLUTE_PROBABILITY_COLUMN in probability.columns
        else "preference_probability"
    )
    _require_columns(
        probability,
        [probability_column],
        context="성별×연령별 선호확률",
    )
    probability["sex_code"] = _as_numeric_finite(
        probability["sex_code"], context="선호확률 성별코드"
    ).astype(int)
    probability["age_code"] = _as_numeric_finite(
        probability["age_code"], context="선호확률 연령코드"
    ).astype(int)
    probability[ABSOLUTE_PROBABILITY_COLUMN] = _as_numeric_finite(
        probability[probability_column],
        context="절대 선호확률",
        nonnegative=True,
    ).astype(float)
    if (probability[ABSOLUTE_PROBABILITY_COLUMN] > 1).any():
        raise ValueError("절대 선호확률은 1을 초과할 수 없습니다.")
    _require_unique(probability, PROBABILITY_KEY, context="성별×연령별 선호확률")

    if set(probability["sex_code"]) != {1, 2}:
        raise ValueError("선호확률 성별코드는 1·2가 모두 존재해야 합니다.")
    if set(probability["age_code"]) != set(range(1, 8)):
        raise ValueError("선호확률 연령코드는 1~7이 모두 존재해야 합니다.")
    actual_categories = set(probability["middle_category"].astype(str))
    if actual_categories != set(MODEL_CATEGORIES):
        raise ValueError(
            "선호확률은 정책 9개 분야와 기타를 포함한 10개 클래스여야 합니다: "
            f"actual={sorted(actual_categories)}"
        )
    expected_rows = 2 * 7 * len(MODEL_CATEGORIES)
    if len(probability) != expected_rows:
        raise ValueError(
            f"성별×연령별 선호확률은 {expected_rows}행이어야 합니다: "
            f"actual={len(probability)}"
        )
    sums = probability.groupby(["sex_code", "age_code"], observed=False)[
        ABSOLUTE_PROBABILITY_COLUMN
    ].sum()
    if not np.allclose(sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError("성별×연령별 10개 클래스 절대확률 합이 1이 아닙니다.")
    return probability


def validate_population_input(population: pd.DataFrame) -> pd.DataFrame:
    """Validate complete 100m grid × sex × model-age target populations."""

    population = population.copy()
    _require_columns(
        population,
        [*POPULATION_KEY, "시군구", "행정동", TARGET_POPULATION_COLUMN],
        context="격자별 성별×연령별 대상자 입력",
    )
    population["GRID_CD"] = population["GRID_CD"].astype("string")
    if population["GRID_CD"].isna().any():
        raise ValueError("격자별 대상자 입력의 GRID_CD에 결측이 있습니다.")
    population["sex_code"] = _as_numeric_finite(
        population["sex_code"], context="격자 성별코드"
    ).astype(int)
    population["model_age_code"] = _as_numeric_finite(
        population["model_age_code"], context="격자 모델 연령코드"
    ).astype(int)
    population[TARGET_POPULATION_COLUMN] = _as_numeric_finite(
        population[TARGET_POPULATION_COLUMN],
        context="격자별 문화누리 대상자 추정인구",
        nonnegative=True,
    ).astype(float)
    _require_unique(population, POPULATION_KEY, context="격자별 성별×연령별 대상자")
    if set(population["sex_code"]) != {1, 2}:
        raise ValueError("격자별 대상자 성별코드는 1·2가 모두 존재해야 합니다.")
    if set(population["model_age_code"]) != set(range(1, 8)):
        raise ValueError("격자별 대상자 모델 연령코드는 1~7이 모두 존재해야 합니다.")

    per_grid_cells = population.groupby("GRID_CD", observed=False).size()
    expected_cells = 2 * 7
    if not per_grid_cells.eq(expected_cells).all():
        incomplete = int((~per_grid_cells.eq(expected_cells)).sum())
        raise ValueError(
            f"성별×연령 14개 셀이 완전하지 않은 격자가 있습니다: {incomplete:,}개"
        )
    if "preference_model_applicable" in population.columns:
        applicable = population["preference_model_applicable"]
        if applicable.dtype != bool:
            applicable = applicable.astype("string").str.lower().map(
                {"true": True, "false": False, "1": True, "0": False}
            )
        if applicable.isna().any() or not bool(applicable.all()):
            raise ValueError("모델 입력에는 15세 이상 적용 가능 셀만 있어야 합니다.")
    return population


def validate_grid_lookup(grid_lookup: pd.DataFrame) -> pd.DataFrame:
    """Validate the grid-to-region lookup without importing accessibility fields."""

    _require_columns(
        grid_lookup,
        GRID_LOOKUP_COLUMNS,
        context="격자 지역 연결표",
    )
    lookup = grid_lookup.loc[:, list(GRID_LOOKUP_COLUMNS)].copy()
    lookup["GRID_CD"] = lookup["GRID_CD"].astype("string")
    lookup["행정동코드"] = (
        pd.to_numeric(lookup["행정동코드"], errors="coerce")
        .astype("Int64")
        .astype("string")
        .str.zfill(8)
    )
    if lookup[["GRID_CD", "행정동코드", "시군구", "행정동"]].isna().any().any():
        raise ValueError("격자 지역 연결표의 코드·지역명에 결측이 있습니다.")
    lookup["중심점_x"] = _as_numeric_finite(
        lookup["중심점_x"], context="격자 중심점 x"
    ).astype(float)
    lookup["중심점_y"] = _as_numeric_finite(
        lookup["중심점_y"], context="격자 중심점 y"
    ).astype(float)
    _require_unique(lookup, ["GRID_CD"], context="격자 지역 연결표")
    return lookup


def build_grid_preference_demand(
    population: pd.DataFrame,
    probability: pd.DataFrame,
    grid_lookup: pd.DataFrame,
    *,
    reference_year: int = REFERENCE_YEAR,
) -> pd.DataFrame:
    """Calculate policy-nine absolute potential demand for every 100m grid."""

    population = validate_population_input(population)
    probability = validate_probability_input(probability)
    lookup = validate_grid_lookup(grid_lookup)

    population_grids = set(population["GRID_CD"])
    lookup_grids = set(lookup["GRID_CD"])
    if population_grids != lookup_grids:
        raise ValueError(
            "대상자 입력과 격자 지역 연결표의 GRID_CD 집합이 다릅니다: "
            f"population_only={len(population_grids - lookup_grids)}, "
            f"lookup_only={len(lookup_grids - population_grids)}"
        )

    label_check = (
        population[["GRID_CD", "시군구", "행정동"]]
        .drop_duplicates()
        .merge(
            lookup[["GRID_CD", "시군구", "행정동"]],
            on="GRID_CD",
            how="left",
            suffixes=("_population", "_lookup"),
            validate="one_to_one",
        )
    )
    label_mismatch = ~(
        label_check["시군구_population"].eq(label_check["시군구_lookup"])
        & label_check["행정동_population"].eq(label_check["행정동_lookup"])
    )
    if label_mismatch.any():
        raise ValueError(
            "대상자 입력과 격자 연결표의 지역명이 일치하지 않습니다: "
            f"{int(label_mismatch.sum()):,}개 격자"
        )

    probability_wide = probability.pivot(
        index=["sex_code", "age_code"],
        columns="middle_category",
        values=ABSOLUTE_PROBABILITY_COLUMN,
    ).reindex(columns=list(MODEL_CATEGORIES))
    probability_wide.columns = [f"probability::{name}" for name in probability_wide]
    probability_wide = probability_wide.reset_index().rename(
        columns={"age_code": "model_age_code"}
    )
    cells = population[[*POPULATION_KEY, TARGET_POPULATION_COLUMN]].merge(
        probability_wide,
        on=["sex_code", "model_age_code"],
        how="left",
        validate="many_to_one",
    )
    probability_columns = [f"probability::{name}" for name in MODEL_CATEGORIES]
    if cells[probability_columns].isna().any().any():
        raise ValueError("격자 인구 셀과 성별×연령 선호확률 결합에 누락이 있습니다.")

    demand_columns: list[str] = []
    for category in MODEL_CATEGORIES:
        demand_column = f"demand::{category}"
        cells[demand_column] = (
            cells[TARGET_POPULATION_COLUMN]
            * cells[f"probability::{category}"]
        )
        demand_columns.append(demand_column)

    grid_wide = (
        cells.groupby("GRID_CD", observed=False)[
            [TARGET_POPULATION_COLUMN, *demand_columns]
        ]
        .sum()
        .reset_index()
        .merge(lookup, on="GRID_CD", how="left", validate="one_to_one")
    )
    policy_demand_columns = [
        f"demand::{category}" for category in PREFERENCE_OUTPUT_CATEGORIES
    ]
    grid_wide["policy_potential_demand_total"] = grid_wide[
        policy_demand_columns
    ].sum(axis=1)
    grid_wide[OTHER_DEMAND_COLUMN] = grid_wide[f"demand::{OTHER_CATEGORY}"]

    target = grid_wide[TARGET_POPULATION_COLUMN].to_numpy(dtype=float)
    policy_total = grid_wide["policy_potential_demand_total"].to_numpy(dtype=float)
    other_demand = grid_wide[OTHER_DEMAND_COLUMN].to_numpy(dtype=float)
    positive_target = target > 0
    positive_policy = policy_total > 0
    parts: list[pd.DataFrame] = []
    for category in PREFERENCE_OUTPUT_CATEGORIES:
        demand = grid_wide[f"demand::{category}"].to_numpy(dtype=float)
        absolute_probability = np.full(len(grid_wide), np.nan, dtype=float)
        conditional_share = np.full(len(grid_wide), np.nan, dtype=float)
        other_probability = np.full(len(grid_wide), np.nan, dtype=float)
        np.divide(demand, target, out=absolute_probability, where=positive_target)
        np.divide(
            demand,
            policy_total,
            out=conditional_share,
            where=positive_policy,
        )
        np.divide(
            other_demand,
            target,
            out=other_probability,
            where=positive_target,
        )
        part = grid_wide[
            [
                "GRID_CD",
                "행정동코드",
                "시군구",
                "행정동",
                "중심점_x",
                "중심점_y",
                TARGET_POPULATION_COLUMN,
                OTHER_DEMAND_COLUMN,
            ]
        ].copy()
        part["middle_category"] = category
        part[ABSOLUTE_PROBABILITY_COLUMN] = absolute_probability
        part[POTENTIAL_DEMAND_COLUMN] = demand
        part[OTHER_PROBABILITY_COLUMN] = other_probability
        part[CONDITIONAL_SHARE_COLUMN] = conditional_share
        part["reference_year"] = int(reference_year)
        part["is_estimate"] = True
        parts.append(part)
    result = pd.concat(parts, ignore_index=True)
    result = result[
        [
            "GRID_CD",
            "행정동코드",
            "시군구",
            "행정동",
            "중심점_x",
            "중심점_y",
            "middle_category",
            TARGET_POPULATION_COLUMN,
            ABSOLUTE_PROBABILITY_COLUMN,
            POTENTIAL_DEMAND_COLUMN,
            OTHER_PROBABILITY_COLUMN,
            OTHER_DEMAND_COLUMN,
            CONDITIONAL_SHARE_COLUMN,
            "reference_year",
            "is_estimate",
        ]
    ]
    _require_unique(result, ["GRID_CD", "middle_category"], context="격자 잠재수요")
    return result


def aggregate_preference_demand(
    grid_demand: pd.DataFrame,
    *,
    level: str,
) -> pd.DataFrame:
    """Aggregate grid estimates using target-population weighted probabilities."""

    if level == "dong":
        region_keys = ["행정동코드", "시군구", "행정동"]
    elif level == "gu":
        working = grid_demand.copy()
        working["자치구코드"] = working["행정동코드"].astype("string").str[:5]
        grid_demand = working
        region_keys = ["자치구코드", "시군구"]
    else:
        raise ValueError("집계 수준은 'dong' 또는 'gu'여야 합니다.")

    _require_columns(
        grid_demand,
        [
            "GRID_CD",
            *region_keys,
            "middle_category",
            TARGET_POPULATION_COLUMN,
            POTENTIAL_DEMAND_COLUMN,
            OTHER_DEMAND_COLUMN,
        ],
        context="격자 잠재수요",
    )
    region_population = (
        grid_demand.drop_duplicates("GRID_CD")
        .groupby(region_keys, observed=False, as_index=False)
        .agg(
            **{
                TARGET_POPULATION_COLUMN: (TARGET_POPULATION_COLUMN, "sum"),
                OTHER_DEMAND_COLUMN: (OTHER_DEMAND_COLUMN, "sum"),
            }
        )
    )
    category_demand = (
        grid_demand.groupby(
            [*region_keys, "middle_category"], observed=False, as_index=False
        )[POTENTIAL_DEMAND_COLUMN]
        .sum()
    )
    result = category_demand.merge(
        region_population,
        on=region_keys,
        how="left",
        validate="many_to_one",
    )
    policy_total = result.groupby(region_keys, observed=False)[
        POTENTIAL_DEMAND_COLUMN
    ].transform("sum")
    target = result[TARGET_POPULATION_COLUMN].to_numpy(dtype=float)
    demand = result[POTENTIAL_DEMAND_COLUMN].to_numpy(dtype=float)
    other_demand = result[OTHER_DEMAND_COLUMN].to_numpy(dtype=float)
    policy_total_array = policy_total.to_numpy(dtype=float)
    result[ABSOLUTE_PROBABILITY_COLUMN] = np.divide(
        demand,
        target,
        out=np.full(len(result), np.nan),
        where=target > 0,
    )
    result[OTHER_PROBABILITY_COLUMN] = np.divide(
        other_demand,
        target,
        out=np.full(len(result), np.nan),
        where=target > 0,
    )
    result[CONDITIONAL_SHARE_COLUMN] = np.divide(
        demand,
        policy_total_array,
        out=np.full(len(result), np.nan),
        where=policy_total_array > 0,
    )
    result["reference_year"] = int(
        pd.to_numeric(grid_demand["reference_year"], errors="raise").iloc[0]
    )
    result["is_estimate"] = True
    return result[
        [
            *region_keys,
            "middle_category",
            TARGET_POPULATION_COLUMN,
            ABSOLUTE_PROBABILITY_COLUMN,
            POTENTIAL_DEMAND_COLUMN,
            OTHER_PROBABILITY_COLUMN,
            OTHER_DEMAND_COLUMN,
            CONDITIONAL_SHARE_COLUMN,
            "reference_year",
            "is_estimate",
        ]
    ].sort_values([*region_keys, "middle_category"], ignore_index=True)


def build_spatial_validation_summary(
    grid_demand: pd.DataFrame,
    dong_demand: pd.DataFrame,
    gu_demand: pd.DataFrame,
    *,
    atol: float = 1e-6,
) -> pd.DataFrame:
    """Return explicit conservation and probability checks for saved outputs."""

    rows: list[dict[str, object]] = []

    def add(check: str, passed: bool, value: object, detail: str) -> None:
        rows.append(
            {
                "check": check,
                "status": "pass" if passed else "fail",
                "value": value,
                "detail": detail,
            }
        )

    grid_base = grid_demand.drop_duplicates("GRID_CD")
    target_total = float(grid_base[TARGET_POPULATION_COLUMN].sum())
    policy_total = float(grid_demand[POTENTIAL_DEMAND_COLUMN].sum())
    other_total = float(grid_base[OTHER_DEMAND_COLUMN].sum())
    add(
        "grid_policy_plus_other_equals_target",
        bool(np.isclose(policy_total + other_total, target_total, atol=atol)),
        float(policy_total + other_total - target_total),
        "정책 9개 잠재수요와 기타 잠재수요 합의 대상자 총량 오차",
    )
    add(
        "grid_category_key_unique",
        not grid_demand.duplicated(["GRID_CD", "middle_category"]).any(),
        int(grid_demand.duplicated(["GRID_CD", "middle_category"]).sum()),
        "GRID_CD×분야 중복 행 수",
    )
    zero_grid = grid_base.loc[grid_base[TARGET_POPULATION_COLUMN].eq(0), "GRID_CD"]
    zero_rows = grid_demand.loc[grid_demand["GRID_CD"].isin(zero_grid)]
    zero_no_data = (
        zero_rows[ABSOLUTE_PROBABILITY_COLUMN].isna().all()
        and zero_rows[CONDITIONAL_SHARE_COLUMN].isna().all()
        and np.isclose(zero_rows[POTENTIAL_DEMAND_COLUMN].sum(), 0.0, atol=atol)
    )
    add(
        "zero_target_grids_are_no_data",
        bool(zero_no_data),
        int(zero_grid.nunique()),
        "대상자 0명 격자는 확률 무자료·잠재수요 0으로 보존",
    )

    positive = grid_demand.loc[grid_demand[TARGET_POPULATION_COLUMN].gt(0)]
    conditional_sums = positive.groupby("GRID_CD", observed=False)[
        CONDITIONAL_SHARE_COLUMN
    ].sum()
    conditional_error = float((conditional_sums - 1.0).abs().max())
    add(
        "grid_conditional_policy_share_sums_to_one",
        bool(conditional_error <= atol),
        conditional_error,
        "대상자 양수 격자의 정책 9개 조건부 구성비 최대 절대오차",
    )

    for name, frame, region_key in (
        ("dong", dong_demand, "행정동코드"),
        ("gu", gu_demand, "자치구코드"),
    ):
        region_base = frame.drop_duplicates(region_key)
        region_target = float(region_base[TARGET_POPULATION_COLUMN].sum())
        region_policy = float(frame[POTENTIAL_DEMAND_COLUMN].sum())
        region_other = float(region_base[OTHER_DEMAND_COLUMN].sum())
        add(
            f"{name}_target_conservation",
            bool(np.isclose(region_target, target_total, atol=atol)),
            float(region_target - target_total),
            f"격자→{name} 대상자 총량 오차",
        )
        add(
            f"{name}_potential_demand_conservation",
            bool(
                np.isclose(region_policy, policy_total, atol=atol)
                and np.isclose(region_other, other_total, atol=atol)
            ),
            float(max(abs(region_policy - policy_total), abs(region_other - other_total))),
            f"격자→{name} 정책·기타 잠재수요 최대 총량 오차",
        )

    summary = pd.DataFrame(rows)
    failures = summary.loc[summary["status"].eq("fail")]
    if not failures.empty:
        raise ValueError(f"공간 수요 정합성 검증 실패:\n{failures.to_string(index=False)}")
    return summary


def build_all_spatial_demand(
    population: pd.DataFrame,
    probability: pd.DataFrame,
    grid_lookup: pd.DataFrame,
    *,
    reference_year: int = REFERENCE_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build grid, dong, gu outputs and their conservation summary."""

    grid = build_grid_preference_demand(
        population,
        probability,
        grid_lookup,
        reference_year=reference_year,
    )
    dong = aggregate_preference_demand(grid, level="dong")
    gu = aggregate_preference_demand(grid, level="gu")
    validation = build_spatial_validation_summary(grid, dong, gu)
    return grid, dong, gu, validation
