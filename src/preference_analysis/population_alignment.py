"""Align 100m grid target-population cells to preference-model age cells.

The source grid table keeps its original 12 age bands.  This module creates a
separate model-aligned table where 70s, 80s, 90s, and 100+ are aggregated to
the survey model's single 70+ cell.  Population below age 15 is retained with
an explicit non-model status and is never silently redistributed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from .modeling import AGE_LABELS, SEX_LABELS


SOURCE_POPULATION_COLUMN: Final = "문화누리대상자_성연령별_추정_인구수"
ALIGNED_POPULATION_COLUMN: Final = "target_population_est"

SOURCE_AGE_ORDER: Final[tuple[str, ...]] = (
    "0-5세",
    "6-14세",
    "15-19세",
    "20-29세",
    "30-39세",
    "40-49세",
    "50-59세",
    "60-69세",
    "70-79세",
    "80-89세",
    "90-99세",
    "100세-",
)

MODEL_READY_STATUS: Final = "선호모형_적용"
UNDER_15_STATUS: Final = "선호모형_미적용"
ELIGIBILITY_REVIEW_STATUS: Final = "대상연령_확인필요"


@dataclass(frozen=True)
class AgeAlignmentRule:
    aligned_age_group: str
    model_age_code: int | None
    alignment_status: str
    alignment_note: str


AGE_ALIGNMENT_RULES: Final[dict[str, AgeAlignmentRule]] = {
    "0-5세": AgeAlignmentRule(
        aligned_age_group="0-5세",
        model_age_code=None,
        alignment_status=ELIGIBILITY_REVIEW_STATUS,
        alignment_note="문화누리 대상연령 적용 여부를 확인한 뒤 총량 포함 여부 결정",
    ),
    "6-14세": AgeAlignmentRule(
        aligned_age_group="6-14세",
        model_age_code=None,
        alignment_status=UNDER_15_STATUS,
        alignment_note="국민여가활동조사 선호모형 연령범위 밖이므로 별도 보존",
    ),
    "15-19세": AgeAlignmentRule("15-19세", 1, MODEL_READY_STATUS, "선호확률 결합 대상"),
    "20-29세": AgeAlignmentRule("20-29세", 2, MODEL_READY_STATUS, "선호확률 결합 대상"),
    "30-39세": AgeAlignmentRule("30-39세", 3, MODEL_READY_STATUS, "선호확률 결합 대상"),
    "40-49세": AgeAlignmentRule("40-49세", 4, MODEL_READY_STATUS, "선호확률 결합 대상"),
    "50-59세": AgeAlignmentRule("50-59세", 5, MODEL_READY_STATUS, "선호확률 결합 대상"),
    "60-69세": AgeAlignmentRule("60-69세", 6, MODEL_READY_STATUS, "선호확률 결합 대상"),
    "70-79세": AgeAlignmentRule("70세 이상", 7, MODEL_READY_STATUS, "70세 이상 선호확률 결합 대상"),
    "80-89세": AgeAlignmentRule("70세 이상", 7, MODEL_READY_STATUS, "70세 이상 선호확률 결합 대상"),
    "90-99세": AgeAlignmentRule("70세 이상", 7, MODEL_READY_STATUS, "70세 이상 선호확률 결합 대상"),
    "100세-": AgeAlignmentRule("70세 이상", 7, MODEL_READY_STATUS, "70세 이상 선호확률 결합 대상"),
}

ALIGNED_AGE_ORDER: Final[tuple[str, ...]] = (
    "0-5세",
    "6-14세",
    "15-19세",
    "20-29세",
    "30-39세",
    "40-49세",
    "50-59세",
    "60-69세",
    "70세 이상",
)

REQUIRED_SOURCE_COLUMNS: Final[set[str]] = {
    "GRID_CD",
    "시군구",
    "행정동",
    "성별",
    "연령대",
    SOURCE_POPULATION_COLUMN,
}


def _validate_source_population(source: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(REQUIRED_SOURCE_COLUMNS - set(source.columns))
    if missing:
        raise ValueError(f"격자 성·연령 대상자 자료에 필요한 열이 없습니다: {missing}")

    working = source[list(REQUIRED_SOURCE_COLUMNS)].copy()
    if working[list(REQUIRED_SOURCE_COLUMNS - {SOURCE_POPULATION_COLUMN})].isna().any().any():
        raise ValueError("격자·지역·성별·연령대 식별 열에 결측값이 있습니다.")

    working[SOURCE_POPULATION_COLUMN] = pd.to_numeric(
        working[SOURCE_POPULATION_COLUMN], errors="coerce"
    )
    if working[SOURCE_POPULATION_COLUMN].isna().any():
        raise ValueError("성·연령별 추정 대상자 수에 결측 또는 숫자 변환 실패가 있습니다.")
    if (working[SOURCE_POPULATION_COLUMN] < 0).any():
        raise ValueError("성·연령별 추정 대상자 수에 음수가 있습니다.")
    if not np.allclose(
        working[SOURCE_POPULATION_COLUMN],
        np.round(working[SOURCE_POPULATION_COLUMN]),
    ):
        raise ValueError("성·연령별 추정 대상자 수는 정수여야 합니다.")
    working[SOURCE_POPULATION_COLUMN] = working[SOURCE_POPULATION_COLUMN].astype(
        np.int64
    )

    unknown_sexes = sorted(set(working["성별"]) - set(SEX_LABELS.values()))
    unknown_ages = sorted(set(working["연령대"]) - set(AGE_ALIGNMENT_RULES))
    if unknown_sexes:
        raise ValueError(f"정의되지 않은 성별 값이 있습니다: {unknown_sexes}")
    if unknown_ages:
        raise ValueError(f"정의되지 않은 연령대 값이 있습니다: {unknown_ages}")

    duplicate_key = ["GRID_CD", "성별", "연령대"]
    duplicate_count = int(working.duplicated(duplicate_key).sum())
    if duplicate_count:
        raise ValueError(
            "격자×성별×연령대 키가 중복됩니다: " f"{duplicate_count:,}행"
        )

    location_counts = working.groupby("GRID_CD")[["시군구", "행정동"]].nunique()
    unstable_locations = int((location_counts.gt(1).any(axis=1)).sum())
    if unstable_locations:
        raise ValueError(
            "하나의 격자코드가 여러 시군구·행정동에 연결됩니다: "
            f"{unstable_locations:,}개"
        )

    expected_cells = len(SEX_LABELS) * len(SOURCE_AGE_ORDER)
    cells_per_grid = working.groupby("GRID_CD").size()
    incomplete_grids = int(cells_per_grid.ne(expected_cells).sum())
    if incomplete_grids:
        raise ValueError(
            "성별 2개×원본 연령대 12개 구성이 완전하지 않은 격자가 있습니다: "
            f"{incomplete_grids:,}개"
        )

    return working


def validate_preference_probability_cells(probabilities: pd.DataFrame) -> None:
    """Validate that all 14 sex-age model cells have proper probabilities."""

    required = {"sex_code", "age_code", "preference_probability"}
    missing = sorted(required - set(probabilities.columns))
    if missing:
        raise ValueError(f"선호확률 자료에 필요한 열이 없습니다: {missing}")

    working = probabilities[list(required)].copy()
    for column in ("sex_code", "age_code", "preference_probability"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    if working.isna().any().any():
        raise ValueError("선호확률 키 또는 확률에 결측·숫자 변환 실패가 있습니다.")
    if (~working["sex_code"].isin(SEX_LABELS)).any():
        raise ValueError("선호확률 자료에 정의되지 않은 성별 코드가 있습니다.")
    if (~working["age_code"].isin(AGE_LABELS)).any():
        raise ValueError("선호확률 자료에 정의되지 않은 연령 코드가 있습니다.")
    if ((working["preference_probability"] < 0) | (working["preference_probability"] > 1)).any():
        raise ValueError("선호확률은 0~1 범위여야 합니다.")

    expected_keys = pd.MultiIndex.from_product(
        [sorted(SEX_LABELS), sorted(AGE_LABELS)], names=["sex_code", "age_code"]
    )
    actual_keys = pd.MultiIndex.from_frame(
        working[["sex_code", "age_code"]].drop_duplicates().astype(int)
    )
    missing_keys = expected_keys.difference(actual_keys)
    extra_keys = actual_keys.difference(expected_keys)
    if len(missing_keys) or len(extra_keys):
        raise ValueError(
            "선호확률의 성별×연령 셀이 완전하지 않습니다: "
            f"누락 {len(missing_keys)}개, 초과 {len(extra_keys)}개"
        )

    probability_sums = working.groupby(["sex_code", "age_code"])[
        "preference_probability"
    ].sum()
    if not np.allclose(probability_sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError("성별×연령별 전체 분야 선호확률 합이 1이 아닙니다.")


def align_grid_sex_age_population(
    source: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return full alignment, model input, age summary, and validation table."""

    working = _validate_source_population(source)
    sex_code_by_label = {label: code for code, label in SEX_LABELS.items()}
    source_age_order = {label: index for index, label in enumerate(SOURCE_AGE_ORDER)}
    aligned_age_order = {label: index for index, label in enumerate(ALIGNED_AGE_ORDER)}

    working["sex_code"] = working["성별"].map(sex_code_by_label).astype(np.int8)
    working["source_age_order"] = working["연령대"].map(source_age_order)
    working["aligned_age_group"] = working["연령대"].map(
        lambda value: AGE_ALIGNMENT_RULES[value].aligned_age_group
    )
    working["model_age_code"] = working["연령대"].map(
        lambda value: AGE_ALIGNMENT_RULES[value].model_age_code
    )
    working["alignment_status"] = working["연령대"].map(
        lambda value: AGE_ALIGNMENT_RULES[value].alignment_status
    )
    working["alignment_note"] = working["연령대"].map(
        lambda value: AGE_ALIGNMENT_RULES[value].alignment_note
    )
    working["model_age_label"] = working["model_age_code"].map(AGE_LABELS)

    group_columns = [
        "GRID_CD",
        "시군구",
        "행정동",
        "sex_code",
        "성별",
        "aligned_age_group",
        "model_age_code",
        "model_age_label",
        "alignment_status",
        "alignment_note",
    ]
    aligned = (
        working.sort_values("source_age_order")
        .groupby(group_columns, as_index=False, dropna=False, observed=False)
        .agg(
            source_age_groups=("연령대", lambda values: "|".join(values)),
            source_age_group_count=("연령대", "size"),
            **{ALIGNED_POPULATION_COLUMN: (SOURCE_POPULATION_COLUMN, "sum")},
        )
    )
    aligned["model_age_code"] = aligned["model_age_code"].astype("Int64")
    aligned["preference_model_applicable"] = aligned["alignment_status"].eq(
        MODEL_READY_STATUS
    )
    aligned["aligned_age_order"] = aligned["aligned_age_group"].map(
        aligned_age_order
    )
    aligned = aligned.sort_values(
        ["GRID_CD", "sex_code", "aligned_age_order"]
    ).reset_index(drop=True)

    source_total = int(working[SOURCE_POPULATION_COLUMN].sum())
    aligned_total = int(aligned[ALIGNED_POPULATION_COLUMN].sum())
    if source_total != aligned_total:
        raise RuntimeError(
            "연령구간 통일 과정에서 대상자 총량이 변했습니다: "
            f"원본 {source_total:,}명, 통일 {aligned_total:,}명"
        )

    model_input = aligned.loc[aligned["preference_model_applicable"]].copy()
    expected_model_cells = len(SEX_LABELS) * len(AGE_LABELS)
    model_cells_per_grid = model_input.groupby("GRID_CD").size()
    incomplete_model_grids = int(model_cells_per_grid.ne(expected_model_cells).sum())
    if incomplete_model_grids:
        raise RuntimeError(
            "성별 2개×모델 연령대 7개 구성이 완전하지 않은 격자가 있습니다: "
            f"{incomplete_model_grids:,}개"
        )

    summary = (
        aligned.groupby(
            [
                "aligned_age_order",
                "aligned_age_group",
                "model_age_code",
                "model_age_label",
                "alignment_status",
                "alignment_note",
            ],
            as_index=False,
            dropna=False,
            observed=False,
        )
        .agg(
            grid_sex_cells=("GRID_CD", "size"),
            target_population_est=(ALIGNED_POPULATION_COLUMN, "sum"),
        )
        .sort_values("aligned_age_order")
        .reset_index(drop=True)
    )
    summary["model_age_code"] = summary["model_age_code"].astype("Int64")

    population_by_status = aligned.groupby("alignment_status")[
        ALIGNED_POPULATION_COLUMN
    ].sum()
    validation_rows = [
        {
            "metric": "source_rows",
            "value": len(working),
            "expected": len(working),
            "status": "pass",
            "note": "원본 성별×연령 행 수",
        },
        {
            "metric": "source_grid_count",
            "value": working["GRID_CD"].nunique(),
            "expected": working["GRID_CD"].nunique(),
            "status": "pass",
            "note": "원본 고유 100m 격자 수",
        },
        {
            "metric": "source_population_total",
            "value": source_total,
            "expected": source_total,
            "status": "pass",
            "note": "통일 전 대상자 총량",
        },
        {
            "metric": "aligned_population_total",
            "value": aligned_total,
            "expected": source_total,
            "status": "pass" if aligned_total == source_total else "fail",
            "note": "통일 후 대상자 총량",
        },
        {
            "metric": "population_conservation_error",
            "value": aligned_total - source_total,
            "expected": 0,
            "status": "pass" if aligned_total == source_total else "fail",
            "note": "통일 후 총량-통일 전 총량",
        },
        {
            "metric": "model_ready_population_total",
            "value": int(population_by_status.get(MODEL_READY_STATUS, 0)),
            "expected": "informational",
            "status": "info",
            "note": "15세 이상 선호확률 결합 대상자",
        },
        {
            "metric": "under_15_unmodeled_population_total",
            "value": int(population_by_status.get(UNDER_15_STATUS, 0)),
            "expected": "informational",
            "status": "info",
            "note": "6~14세 선호모형 미적용 대상자",
        },
        {
            "metric": "eligibility_review_population_total",
            "value": int(population_by_status.get(ELIGIBILITY_REVIEW_STATUS, 0)),
            "expected": "review_required",
            "status": "review",
            "note": "0~5세 대상연령 포함 여부 확인 필요",
        },
        {
            "metric": "incomplete_model_grid_count",
            "value": incomplete_model_grids,
            "expected": 0,
            "status": "pass" if incomplete_model_grids == 0 else "fail",
            "note": "성별 2개×모델 연령 7개 미완전 격자",
        },
    ]
    validation = pd.DataFrame(validation_rows)

    output_columns = [
        "GRID_CD",
        "시군구",
        "행정동",
        "sex_code",
        "성별",
        "aligned_age_order",
        "aligned_age_group",
        "model_age_code",
        "model_age_label",
        "preference_model_applicable",
        "alignment_status",
        "alignment_note",
        "source_age_groups",
        "source_age_group_count",
        ALIGNED_POPULATION_COLUMN,
    ]
    return aligned[output_columns], model_input[output_columns], summary, validation
