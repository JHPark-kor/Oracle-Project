"""Map National Leisure Activity Survey activity codes to MNC categories.

The raw activity code and raw activity label are preserved.  The mapping only
adds model-category columns; it never rewrites the three satisfaction-rank
source columns.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


SATISFACTION_RANK_COLUMNS: tuple[str, ...] = (
    "가장 만족스러운 여가활동 1순위",
    "가장 만족스러운 여가활동 2순위",
    "가장 만족스러운 여가활동 3순위",
)

FUTURE_PREFERENCE_COLUMNS: tuple[str, ...] = (
    "향후 희망하는 여가활동 1순위",
    "향후 희망하는 여가활동 2순위",
    "향후 희망하는 여가활동 3순위",
)

MODEL_BASE_COLUMNS: tuple[str, ...] = (
    "조사년도",
    "성별",
    "연령",
    "가구소득",
    "지역규모",
    "17개 시도",
    "최종가중치",
)

OTHER_CATEGORY = "기타·문화누리 비대응"

PREFERENCE_OUTPUT_CATEGORIES: tuple[str, ...] = (
    "도서",
    "영상",
    "공연",
    "미술",
    "문화체험",
    "관광지",
    "스포츠관람",
    "체육시설",
)

# These merchant categories remain available to the supply/accessibility
# pipeline, but the leisure survey has no defensible direct preference label.
# They must not be emitted with a fabricated zero probability.
UNMODELED_PREFERENCE_CATEGORIES = frozenset({"체육용품"})

# Radio/podcast and streaming-listening activities do not represent demand for
# a local, accessibility-sensitive MNC merchant.  Preserve their survey weight
# in the residual class instead of dropping the observations or fabricating a
# zero probability.
POLICY_EXCLUDED_PREFERENCE_CATEGORIES = frozenset({"음악"})

MODEL_CATEGORIES: tuple[str, ...] = (
    *PREFERENCE_OUTPUT_CATEGORIES,
    OTHER_CATEGORY,
)

# This is the previously agreed 13-way activity classification.  It is kept
# separately from the model category so that exclusions remain auditable.
LEGACY_ACTIVITY_CODES: dict[str, frozenset[int]] = {
    "도서": frozenset({65, 66, 78}),
    "음악": frozenset({76, 77}),
    "영상": frozenset({7, 17, 74, 75}),
    "공연": frozenset({3, 4, 5, 6, 8}),
    "미술": frozenset({1, 2, 14}),
    "문화체험": frozenset({9, 10, 11, 12, 13, 15, 50, 51, 69}),
    "교통수단": frozenset({48}),
    "여행사": frozenset({42}),
    "관광지": frozenset({38, 39, 40, 41, 43, 44, 45, 46, 47, 55, 72}),
    "스포츠 관람": frozenset({16, 18, 19}),
    "체육용품": frozenset({35}),
    "체육시설": frozenset(
        {20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 36, 37, 56}
    ),
    "분류범위외": frozenset(
        {
            49,
            52,
            53,
            54,
            57,
            58,
            59,
            60,
            61,
            62,
            63,
            64,
            67,
            68,
            70,
            71,
            73,
            79,
            80,
            81,
            82,
            83,
            84,
            85,
            86,
            87,
            88,
        }
    ),
}

OUTSIDE_SCOPE_SURVEY_CATEGORIES = frozenset({"교통수단", "여행사", "분류범위외"})
EXCLUDED_MODEL_CATEGORIES = (
    OUTSIDE_SCOPE_SURVEY_CATEGORIES
    | UNMODELED_PREFERENCE_CATEGORIES
    | POLICY_EXCLUDED_PREFERENCE_CATEGORIES
)

# Keep the original classified workbook's label in legacy_middle_category,
# while using the compact label already agreed for downstream model outputs.
MODEL_CATEGORY_BY_LEGACY = {"스포츠 관람": "스포츠관람"}

_ACTIVITY_COLUMN_PATTERN = re.compile(
    r"^한 번 이상 참여한 여가활동 - \((?P<code>\d+)\) (?P<name>.+)$"
)


def _reverse_unique_mapping(mapping: dict[str, frozenset[int]]) -> dict[int, str]:
    reverse: dict[int, str] = {}
    duplicates: list[int] = []
    for category, codes in mapping.items():
        for code in codes:
            if code in reverse:
                duplicates.append(code)
            reverse[code] = category
    if duplicates:
        raise ValueError(f"중복 분류된 활동코드가 있습니다: {sorted(set(duplicates))}")
    return reverse


LEGACY_CATEGORY_BY_CODE = _reverse_unique_mapping(LEGACY_ACTIVITY_CODES)


def validate_mapping_spec() -> None:
    expected = set(range(1, 89))
    actual = set(LEGACY_CATEGORY_BY_CODE)
    if actual != expected:
        raise ValueError(
            "활동코드 매핑은 1~88을 정확히 한 번씩 포함해야 합니다: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def extract_activity_catalog(columns: Iterable[str]) -> pd.DataFrame:
    """Extract the exact raw code/name pairs from the 88 participation headers."""

    rows: list[dict[str, object]] = []
    for column in columns:
        match = _ACTIVITY_COLUMN_PATTERN.match(str(column))
        if not match:
            continue
        rows.append(
            {
                "activity_code": int(match.group("code")),
                "activity_name_original": match.group("name"),
                "source_column_original": str(column),
            }
        )

    catalog = pd.DataFrame(rows).sort_values("activity_code").reset_index(drop=True)
    if catalog.empty:
        raise ValueError("원본 설문에서 88개 여가활동 열을 찾지 못했습니다.")
    if catalog["activity_code"].duplicated().any():
        duplicated = catalog.loc[
            catalog["activity_code"].duplicated(keep=False), "activity_code"
        ].tolist()
        raise ValueError(f"원본 설문 활동코드 열이 중복됩니다: {duplicated}")

    expected = set(range(1, 89))
    actual = set(catalog["activity_code"])
    if actual != expected:
        raise ValueError(
            "원본 설문 활동열은 코드 1~88을 정확히 포함해야 합니다: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    return catalog


def build_activity_mapping(leisure_path: str | Path) -> pd.DataFrame:
    """Build the canonical mapping while preserving raw code/name values."""

    validate_mapping_spec()
    header = pd.read_csv(leisure_path, nrows=0, encoding="utf-8-sig")
    mapping = extract_activity_catalog(header.columns)
    mapping["legacy_middle_category"] = mapping["activity_code"].map(
        LEGACY_CATEGORY_BY_CODE
    )
    mapping["model_middle_category"] = mapping["legacy_middle_category"].map(
        lambda category: (
            OTHER_CATEGORY
            if category in EXCLUDED_MODEL_CATEGORIES
            else MODEL_CATEGORY_BY_LEGACY.get(category, category)
        )
    )
    mapping["mapping_status"] = np.where(
        mapping["legacy_middle_category"].isin(EXCLUDED_MODEL_CATEGORIES),
        "기타로 통합",
        "기존 분류 유지",
    )
    mapping["preference_model_status"] = np.select(
        [
            mapping["legacy_middle_category"].isin(
                UNMODELED_PREFERENCE_CATEGORIES
            ),
            mapping["legacy_middle_category"].isin(
                POLICY_EXCLUDED_PREFERENCE_CATEGORIES
            ),
            mapping["legacy_middle_category"].isin(
                OUTSIDE_SCOPE_SURVEY_CATEGORIES
            ),
        ],
        [
            "미산출(직접 선호라벨 부족)",
            "정책범위 제외(기타 선택지로 통합)",
            "분석범위외(기타 선택지로 통합)",
        ],
        default="선호확률 산출",
    )
    mapping["include_in_policy_category"] = mapping["model_middle_category"].ne(
        OTHER_CATEGORY
    )
    return mapping


def _normalise_rank_code(series: pd.Series, column: str) -> pd.Series:
    stripped = series.astype("string").str.strip()
    numeric = pd.to_numeric(stripped, errors="coerce")
    invalid_nonempty = stripped.notna() & stripped.ne("") & numeric.isna()
    invalid_range = numeric.notna() & ~numeric.between(1, 88)
    invalid_fraction = numeric.notna() & numeric.ne(np.floor(numeric))
    invalid = invalid_nonempty | invalid_range | invalid_fraction
    if invalid.any():
        examples = stripped.loc[invalid].drop_duplicates().head(10).tolist()
        raise ValueError(f"{column}에 1~88 이외의 활동코드가 있습니다: {examples}")
    return numeric.astype("Int64")


def transform_satisfaction_ranks(
    leisure_path: str | Path,
    mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Add original activity names and model categories to satisfaction ranks.

    Returns the transformed model table, validation summary, and annual/rank
    category distribution.  Future-preference fields are intentionally absent.
    """

    required = [*MODEL_BASE_COLUMNS, *SATISFACTION_RANK_COLUMNS]
    header = pd.read_csv(leisure_path, nrows=0, encoding="utf-8-sig")
    missing = sorted(set(required) - set(header.columns))
    if missing:
        raise ValueError(f"국민여가활동조사 필수 열이 없습니다: {missing}")

    source = pd.read_csv(
        leisure_path,
        usecols=required,
        dtype={column: "string" for column in SATISFACTION_RANK_COLUMNS},
        encoding="utf-8-sig",
        low_memory=False,
    )
    output = source.copy()
    output.insert(0, "source_row_index", np.arange(len(output), dtype=np.int64))

    code_to_name = mapping.set_index("activity_code")["activity_name_original"].to_dict()
    code_to_category = mapping.set_index("activity_code")["model_middle_category"].to_dict()

    original_code_mismatches = 0
    unmapped_values = 0
    for rank, column in enumerate(SATISFACTION_RANK_COLUMNS, start=1):
        original = source[column].copy()
        code = _normalise_rank_code(source[column], column)
        output[column] = code
        output[f"만족활동_{rank}순위_원본활동명"] = code.map(code_to_name).astype("string")
        output[f"만족활동_{rank}순위_중분류"] = code.map(code_to_category).astype("string")

        round_trip = output[column].astype("string")
        original_normalised = _normalise_rank_code(original, column).astype("string")
        original_code_mismatches += int(
            (~round_trip.fillna("<NA>").eq(original_normalised.fillna("<NA>"))).sum()
        )
        unmapped_values += int(
            (
                code.notna()
                & (
                    output[f"만족활동_{rank}순위_원본활동명"].isna()
                    | output[f"만족활동_{rank}순위_중분류"].isna()
                )
            )
            .sum()
        )

    future_columns_in_output = len(set(FUTURE_PREFERENCE_COLUMNS) & set(output.columns))
    rank_code_columns = list(SATISFACTION_RANK_COLUMNS)
    repeated_original_code_rows = int(
        output[rank_code_columns]
        .apply(
            lambda row: row.dropna().duplicated().any(),
            axis=1,
        )
        .sum()
    )
    validation_rows: list[dict[str, object]] = [
        {
            "check": "mapping_activity_code_coverage",
            "status": "pass" if len(mapping) == 88 else "fail",
            "value": len(mapping),
            "detail": "매핑표가 원본 활동코드 1~88을 정확히 포함하는지",
        },
        {
            "check": "source_rows_preserved",
            "status": "pass" if len(output) == len(source) else "fail",
            "value": len(output),
            "detail": "변환 전후 응답자 행 수",
        },
        {
            "check": "original_rank_code_mismatches",
            "status": "pass" if original_code_mismatches == 0 else "fail",
            "value": original_code_mismatches,
            "detail": "만족활동 1~3순위 원본코드 왕복 비교 불일치 건수",
        },
        {
            "check": "unmapped_satisfaction_values",
            "status": "pass" if unmapped_values == 0 else "fail",
            "value": unmapped_values,
            "detail": "유효 만족활동 코드 중 활동명 또는 중분류 미매핑 건수",
        },
        {
            "check": "future_preference_columns_in_output",
            "status": "pass" if future_columns_in_output == 0 else "fail",
            "value": future_columns_in_output,
            "detail": "향후 희망활동 열이 결과에서 완전히 제외됐는지",
        },
        {
            "check": "repeated_original_activity_code_across_ranks",
            "status": "warning" if repeated_original_code_rows else "pass",
            "value": repeated_original_code_rows,
            "detail": (
                "동일 응답자의 만족활동 순위 간 동일 원 활동코드 반복; "
                "오류로 제외하지 않고 3:2:1 점수를 합산"
            ),
        },
    ]

    for rank, column in enumerate(SATISFACTION_RANK_COLUMNS, start=1):
        missing_count = int(output[column].isna().sum())
        validation_rows.append(
            {
                "check": f"satisfaction_rank_{rank}_missing",
                "status": "warning" if missing_count else "pass",
                "value": missing_count,
                "detail": "원자료의 구조적/응답 결측이며 모델별 학습 시 해당 행만 제외",
            }
        )

    validation = pd.DataFrame(validation_rows)
    failures = validation.loc[validation["status"].eq("fail")]
    if not failures.empty:
        raise ValueError(f"만족활동 매핑 검증 실패:\n{failures.to_string(index=False)}")

    long_parts: list[pd.DataFrame] = []
    for rank, column in enumerate(SATISFACTION_RANK_COLUMNS, start=1):
        part = output[["조사년도", "최종가중치", column]].copy()
        part["rank"] = rank
        part["middle_category"] = output[f"만족활동_{rank}순위_중분류"]
        part["최종가중치"] = pd.to_numeric(part["최종가중치"], errors="coerce")
        part = part.loc[part[column].notna()].copy()
        long_parts.append(part)
    long = pd.concat(long_parts, ignore_index=True)
    distribution = (
        long.groupby(["조사년도", "rank", "middle_category"], dropna=False)
        .agg(response_count=("rank", "size"), weighted_count=("최종가중치", "sum"))
        .reset_index()
    )
    distribution["weighted_share"] = distribution["weighted_count"] / distribution.groupby(
        ["조사년도", "rank"]
    )["weighted_count"].transform("sum")

    return output, validation, distribution
