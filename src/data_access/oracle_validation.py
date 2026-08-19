"""로컬 계산결과와 Oracle 조회결과의 값 일치 검증 도구."""

from __future__ import annotations

from typing import Iterable, Mapping

import pandas as pd


def compare_keyed_numeric_frames(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    key_columns: Iterable[str],
    numeric_columns: Iterable[str],
    context: str,
    absolute_tolerances: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """두 테이블의 키·행 수·숫자값을 순서와 무관하게 비교한다.

    기본 허용오차는 0이므로 정수와 금액은 완전일치해야 한다. Oracle NUMBER와
    Python float 표현 차이가 가능한 비율 열만 호출자가 명시적으로 허용한다.
    """

    keys = list(key_columns)
    values = list(numeric_columns)
    tolerances = dict(absolute_tolerances or {})
    unknown_tolerances = sorted(set(tolerances) - set(values))
    if unknown_tolerances:
        raise ValueError(
            f"{context} 비교 대상이 아닌 허용오차 열입니다: {unknown_tolerances}"
        )
    if any(value < 0 for value in tolerances.values()):
        raise ValueError(f"{context} 허용오차는 0 이상이어야 합니다.")
    required = keys + values
    for name, frame in (("local", expected), ("oracle", actual)):
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"{context} {name} 필수 열이 없습니다: {missing}")
        if frame.duplicated(keys).any():
            raise ValueError(f"{context} {name}에 중복 키가 있습니다: {keys}")

    local = expected[required].copy()
    oracle = actual[required].copy()
    joined = local.merge(
        oracle,
        on=keys,
        how="outer",
        validate="1:1",
        suffixes=("_local", "_oracle"),
        indicator=True,
    )
    missing_local = int((joined["_merge"] == "right_only").sum())
    missing_oracle = int((joined["_merge"] == "left_only").sum())
    max_differences: dict[str, float] = {}
    mismatch_by_column: dict[str, int] = {}
    mismatch_rows = pd.Series(False, index=joined.index)
    for column in values:
        local_values = pd.to_numeric(joined[f"{column}_local"], errors="coerce")
        oracle_values = pd.to_numeric(joined[f"{column}_oracle"], errors="coerce")
        difference = (local_values - oracle_values).abs()
        max_differences[column] = float(difference.max()) if difference.notna().any() else 0.0
        both_null = local_values.isna() & oracle_values.isna()
        one_null = local_values.isna() ^ oracle_values.isna()
        tolerance = tolerances.get(column, 0.0)
        column_mismatch = one_null | (~both_null & difference.gt(tolerance))
        mismatch_by_column[column] = int(column_mismatch.sum())
        mismatch_rows |= column_mismatch

    result: dict[str, object] = {
        "context": context,
        "local_rows": len(local),
        "oracle_rows": len(oracle),
        "missing_from_local": missing_local,
        "missing_from_oracle": missing_oracle,
        "numeric_mismatch_rows": int(mismatch_rows.sum()),
        "numeric_mismatch_by_column": mismatch_by_column,
        "max_absolute_difference": max_differences,
        "absolute_tolerance": {
            column: tolerances.get(column, 0.0) for column in values
        },
    }
    result["passed"] = (
        len(local) == len(oracle)
        and missing_local == 0
        and missing_oracle == 0
        and not mismatch_rows.any()
    )
    return result
