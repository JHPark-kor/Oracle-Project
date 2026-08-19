"""선호확률과 100m 잠재수요를 Oracle 적재 형태로 검증·변환한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.data_access.card_usage import MIDDLE_CATEGORY_CODES, MIDDLE_SCHEME
from src.preference_analysis.mapping import (
    MODEL_CATEGORIES,
    OTHER_CATEGORY,
    PREFERENCE_OUTPUT_CATEGORIES,
)
from src.preference_analysis.spatial_demand import validate_probability_input


PIPELINE_NAME = "preference_spatial_2024_v1"
REFERENCE_YEAR = 2024
PREFERENCE_SCHEME = "PREFERENCE_V1"
PREFERENCE_CATEGORY_CODES = {
    category: (f"P{index:02d}" if category != OTHER_CATEGORY else "P99")
    for index, category in enumerate(MODEL_CATEGORIES, start=1)
}

ORACLE_PROBABILITY_COLUMNS = [
    "reference_year",
    "sex_code",
    "sex_label",
    "age_code",
    "age_label",
    "scheme_code",
    "category_code",
    "absolute_probability",
    "other_probability",
    "conditional_share",
    "policy_flag",
]

ORACLE_GRID_DEMAND_COLUMNS = [
    "reference_year",
    "grid_cd",
    "scheme_code",
    "category_code",
    "target_population_est",
    "absolute_probability",
    "potential_demand",
    "other_probability",
    "other_potential_demand",
    "conditional_share",
    "estimate_flag",
]


def build_preference_category_rows() -> list[dict[str, Any]]:
    rows = []
    for display_order, category in enumerate(MODEL_CATEGORIES, start=1):
        rows.append(
            {
                "scheme_code": PREFERENCE_SCHEME,
                "category_code": PREFERENCE_CATEGORY_CODES[category],
                "category_name": category,
                "display_order": display_order,
                "supported_flag": "Y" if category != OTHER_CATEGORY else "N",
                "valid_from_year": 2024,
            }
        )
    return rows


def build_preference_supply_bridge_rows() -> list[dict[str, Any]]:
    """선호 8개와 공급 13개 중 같은 분야만 직접 연결한다."""

    return [
        {
            "from_scheme_code": PREFERENCE_SCHEME,
            "from_category_code": PREFERENCE_CATEGORY_CODES[category],
            "to_scheme_code": MIDDLE_SCHEME,
            "to_category_code": MIDDLE_CATEGORY_CODES[category],
            "mapping_weight": 1.0,
            "mapping_status": "DIRECT",
            "mapping_note": "선호 정책분야와 공급 중분류의 동일 명칭 직접 연결",
        }
        for category in PREFERENCE_OUTPUT_CATEGORIES
    ]


def load_preference_probability(path: str | Path) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig")
    validated = validate_probability_input(raw)
    required = {
        "sex_label",
        "age_label",
        "survey_year",
        "other_probability_absolute",
        "preference_share_conditional_mnc",
    }
    missing = sorted(required - set(validated.columns))
    if missing:
        raise ValueError(f"선호확률 산출물에 필요한 열이 없습니다: {missing}")
    if set(pd.to_numeric(validated["survey_year"], errors="raise")) != {2024}:
        raise ValueError("공간 적용용 선호확률 기준연도는 2024여야 합니다.")

    policy_mask = validated["middle_category"].isin(PREFERENCE_OUTPUT_CATEGORIES)
    conditional = pd.to_numeric(
        validated["preference_share_conditional_mnc"], errors="coerce"
    )
    if conditional[policy_mask].isna().any() or conditional[~policy_mask].notna().any():
        raise ValueError("정책분야 조건부 구성비 또는 기타분야 결측 규칙이 다릅니다.")
    conditional_sums = (
        validated.loc[policy_mask]
        .assign(_conditional=conditional[policy_mask])
        .groupby(["sex_code", "age_code"])["_conditional"]
        .sum()
    )
    if not np.allclose(conditional_sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError("성별×연령별 정책 8개 조건부 구성비 합이 1이 아닙니다.")

    result = pd.DataFrame(
        {
            "reference_year": REFERENCE_YEAR,
            "sex_code": validated["sex_code"].astype("int64"),
            "sex_label": validated["sex_label"].astype("string"),
            "age_code": validated["age_code"].astype("int64"),
            "age_label": validated["age_label"].astype("string"),
            "scheme_code": PREFERENCE_SCHEME,
            "category_code": validated["middle_category"].map(
                PREFERENCE_CATEGORY_CODES
            ),
            "absolute_probability": validated[
                "preference_probability_absolute"
            ].astype(float),
            "other_probability": pd.to_numeric(
                validated["other_probability_absolute"], errors="raise"
            ).astype(float),
            "conditional_share": conditional.astype(float),
            "policy_flag": np.where(policy_mask, "Y", "N"),
        }
    )
    return result[ORACLE_PROBABILITY_COLUMNS].sort_values(
        ["sex_code", "age_code", "category_code"]
    ).reset_index(drop=True)


def load_grid_preference_demand(path: str | Path) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    required = {
        "GRID_CD",
        "middle_category",
        "target_population_est",
        "preference_probability_absolute",
        "potential_demand_absolute",
        "other_probability_absolute",
        "other_potential_demand",
        "preference_share_conditional_mnc",
        "reference_year",
        "is_estimate",
    }
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"격자 선호 잠재수요에 필요한 열이 없습니다: {missing}")
    if len(raw) != 484_224 or raw["GRID_CD"].nunique() != 60_528:
        raise ValueError(
            "격자 선호 잠재수요 행·격자 수가 다릅니다: "
            f"rows={len(raw):,}, grids={raw['GRID_CD'].nunique():,}"
        )
    if set(raw["middle_category"].astype(str)) != set(PREFERENCE_OUTPUT_CATEGORIES):
        raise ValueError("격자 잠재수요는 정책 8개 분야만 포함해야 합니다.")
    if raw.duplicated(["GRID_CD", "middle_category"]).any():
        raise ValueError("격자×정책분야 키가 중복됩니다.")
    if set(pd.to_numeric(raw["reference_year"], errors="raise")) != {2024}:
        raise ValueError("격자 잠재수요 기준연도는 2024여야 합니다.")
    if not raw.groupby("GRID_CD").size().eq(8).all():
        raise ValueError("정책 8개 분야가 완전하지 않은 격자가 있습니다.")

    numeric_columns = [
        "target_population_est",
        "preference_probability_absolute",
        "potential_demand_absolute",
        "other_probability_absolute",
        "other_potential_demand",
        "preference_share_conditional_mnc",
    ]
    for column in numeric_columns:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    always_required = [
        "target_population_est",
        "potential_demand_absolute",
        "other_potential_demand",
    ]
    if raw[always_required].isna().any().any():
        raise ValueError("격자 잠재수요의 필수 수치열에 결측이 있습니다.")
    finite_required = np.isfinite(raw[always_required].to_numpy(dtype=float)).all()
    if not finite_required or (raw[always_required] < 0).any(axis=None):
        raise ValueError("격자 잠재수요의 필수 수치열에 음수 또는 무한대가 있습니다.")

    positive = raw["target_population_est"] > 0
    optional = [
        "preference_probability_absolute",
        "other_probability_absolute",
        "preference_share_conditional_mnc",
    ]
    if raw.loc[positive, optional].isna().any().any():
        raise ValueError("대상자 양수 격자의 확률·구성비에 결측이 있습니다.")
    if raw.loc[~positive, optional].notna().any().any():
        raise ValueError("대상자 0명 격자의 확률은 무자료여야 합니다.")
    for column in optional:
        valid = raw.loc[positive, column]
        if (~valid.between(0, 1)).any() or not np.isfinite(valid).all():
            raise ValueError(f"{column}이 0~1 범위를 벗어났습니다.")

    target_by_grid = raw.groupby("GRID_CD")["target_population_est"]
    if target_by_grid.nunique().gt(1).any():
        raise ValueError("같은 격자의 분야별 대상자 수가 다릅니다.")
    other_by_grid = raw.groupby("GRID_CD")["other_potential_demand"]
    if other_by_grid.nunique().gt(1).any():
        raise ValueError("같은 격자의 분야별 기타 잠재수요가 다릅니다.")
    target_total = float(target_by_grid.first().sum())
    policy_total = float(raw["potential_demand_absolute"].sum())
    other_total = float(other_by_grid.first().sum())
    if not np.isclose(target_total, 545_692.0, atol=1e-6):
        raise ValueError(f"15세 이상 대상자 총량이 다릅니다: {target_total}")
    if not np.isclose(policy_total + other_total, target_total, atol=1e-6):
        raise ValueError("정책 8개 잠재수요와 기타 잠재수요 합이 대상자와 다릅니다.")
    conditional_sum = raw.loc[positive].groupby("GRID_CD")[
        "preference_share_conditional_mnc"
    ].sum()
    if not np.allclose(conditional_sum.to_numpy(), 1.0, atol=1e-8):
        raise ValueError("대상자 양수 격자의 정책 8개 조건부 구성비 합이 1이 아닙니다.")

    estimate_text = raw["is_estimate"].astype("string").str.strip().str.lower()
    estimate_flag = estimate_text.map(
        {"true": "Y", "1": "Y", "yes": "Y", "false": "N", "0": "N", "no": "N"}
    )
    if estimate_flag.isna().any():
        raise ValueError("is_estimate 값은 True/False 형태여야 합니다.")

    result = pd.DataFrame(
        {
            "reference_year": REFERENCE_YEAR,
            "grid_cd": raw["GRID_CD"].astype("string"),
            "scheme_code": PREFERENCE_SCHEME,
            "category_code": raw["middle_category"].map(
                PREFERENCE_CATEGORY_CODES
            ),
            "target_population_est": raw["target_population_est"].astype(float),
            "absolute_probability": raw[
                "preference_probability_absolute"
            ].astype(float),
            "potential_demand": raw["potential_demand_absolute"].astype(float),
            "other_probability": raw["other_probability_absolute"].astype(float),
            "other_potential_demand": raw["other_potential_demand"].astype(float),
            "conditional_share": raw[
                "preference_share_conditional_mnc"
            ].astype(float),
            "estimate_flag": estimate_flag,
        }
    )
    return result[ORACLE_GRID_DEMAND_COLUMNS].sort_values(
        ["grid_cd", "category_code"]
    ).reset_index(drop=True)


def prepare_preference_for_oracle(
    probability_path: str | Path,
    grid_demand_path: str | Path,
) -> dict[str, Any]:
    probability = load_preference_probability(probability_path)
    grid_demand = load_grid_preference_demand(grid_demand_path)
    return {
        "category_rows": build_preference_category_rows(),
        "bridge_rows": build_preference_supply_bridge_rows(),
        "probability": probability,
        "grid_demand": grid_demand,
    }


def _oracle_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def iter_frame_records(
    frame: pd.DataFrame,
    *,
    etl_run_id: int,
    chunk_size: int = 10_000,
) -> Iterable[list[dict[str, Any]]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")
    columns = list(frame.columns)
    for start in range(0, len(frame), chunk_size):
        chunk = frame.iloc[start : start + chunk_size]
        yield [
            {
                "etl_run_id": etl_run_id,
                **{
                    column: _oracle_value(value)
                    for column, value in zip(columns, row, strict=True)
                },
            }
            for row in chunk.itertuples(index=False, name=None)
        ]


# ---------------------------------------------------------------------------
# 기존 local/Oracle 조회 호환 계층
# ---------------------------------------------------------------------------

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.preference_analysis.mapping import (
    MODEL_CATEGORIES,
    OTHER_CATEGORY,
    PREFERENCE_OUTPUT_CATEGORIES,
)


PROBABILITY_COLUMNS = [
    "sex_code",
    "sex_label",
    "age_code",
    "age_label",
    "sex_age_code",
    "survey_year",
    "middle_category",
    "preference_probability",
    "preference_probability_absolute",
    "other_probability_absolute",
    "preference_share_conditional_mnc",
    "is_policy_category",
]

GRID_DEMAND_COLUMNS = [
    "GRID_CD",
    "행정동코드",
    "시군구",
    "행정동",
    "중심점_x",
    "중심점_y",
    "middle_category",
    "target_population_est",
    "preference_probability_absolute",
    "potential_demand_absolute",
    "other_probability_absolute",
    "other_potential_demand",
    "preference_share_conditional_mnc",
    "reference_year",
    "is_estimate",
]


def _coerce_bool(series: pd.Series, *, context: str) -> pd.Series:
    if series.dtype == bool:
        return series.astype(bool)
    converted = (
        series.astype("string")
        .str.strip()
        .str.lower()
        .map(
            {
                "true": True,
                "1": True,
                "y": True,
                "yes": True,
                "false": False,
                "0": False,
                "n": False,
                "no": False,
            }
        )
    )
    if converted.isna().any():
        raise ValueError(f"{context} 값이 True/False 형태가 아닙니다.")
    return converted.astype(bool)


def _validate_probability(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(PROBABILITY_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"성별×연령별 선호확률 열이 없습니다: {missing}")
    result = frame[PROBABILITY_COLUMNS].copy()
    for column in (
        "sex_code",
        "age_code",
        "survey_year",
        "preference_probability",
        "preference_probability_absolute",
        "other_probability_absolute",
        "preference_share_conditional_mnc",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if len(result) != 126:
        raise ValueError(f"성별×연령별 선호확률 행 수가 다릅니다: {len(result):,}")
    if result.duplicated(["sex_code", "age_code", "middle_category"]).any():
        raise ValueError("성별×연령×선호분류 키가 중복됩니다.")
    if set(result["middle_category"].astype(str)) != set(MODEL_CATEGORIES):
        raise ValueError(
            "선호확률은 정책 8개와 기타를 합한 9개 클래스여야 합니다."
        )
    absolute = result["preference_probability_absolute"]
    if absolute.isna().any() or (~absolute.between(0, 1)).any():
        raise ValueError("선호 절대확률에 결측 또는 범위 밖 값이 있습니다.")
    other_probability = result["other_probability_absolute"]
    if other_probability.isna().any() or (~other_probability.between(0, 1)).any():
        raise ValueError("기타 절대확률에 결측 또는 범위 밖 값이 있습니다.")
    if set(result["survey_year"].dropna().astype(int)) != {2024}:
        raise ValueError("성별×연령별 선호확률 기준연도는 2024여야 합니다.")
    expected_sex_age = (
        result["sex_code"].astype("Int64").astype("string")
        + "_"
        + result["age_code"].astype("Int64").astype("string")
    )
    if not result["sex_age_code"].astype("string").equals(expected_sex_age):
        raise ValueError("sex_age_code가 성별·연령 코드와 다릅니다.")
    absolute_sums = result.groupby(["sex_code", "age_code"])[
        "preference_probability_absolute"
    ].sum()
    if not np.allclose(absolute_sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError("성별×연령별 9개 클래스 절대확률 합이 1이 아닙니다.")
    if not np.allclose(
        result["preference_probability"],
        result["preference_probability_absolute"],
        atol=1e-12,
    ):
        raise ValueError("preference_probability와 절대확률 값이 다릅니다.")
    other_mask = result["middle_category"].eq(OTHER_CATEGORY)
    if not np.allclose(
        result.loc[other_mask, "preference_probability_absolute"],
        result.loc[other_mask, "other_probability_absolute"],
        atol=1e-12,
    ):
        raise ValueError("기타 클래스 절대확률과 기타확률 값이 다릅니다.")
    policy = result["middle_category"].isin(PREFERENCE_OUTPUT_CATEGORIES)
    policy_flag = _coerce_bool(
        result["is_policy_category"], context="is_policy_category"
    )
    if not policy_flag.equals(policy):
        raise ValueError("정책분야 여부가 중분류 정의와 다릅니다.")
    conditional = result["preference_share_conditional_mnc"]
    if conditional[policy].isna().any() or conditional[~policy].notna().any():
        raise ValueError("정책분야 조건부 구성비의 결측 규칙이 다릅니다.")
    conditional_sums = result.loc[policy].groupby(["sex_code", "age_code"])[
        "preference_share_conditional_mnc"
    ].sum()
    if not np.allclose(conditional_sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError(
            "성별×연령별 정책 8개 조건부 구성비 합이 1이 아닙니다."
        )
    result["sex_code"] = result["sex_code"].astype("int64")
    result["age_code"] = result["age_code"].astype("int64")
    result["survey_year"] = result["survey_year"].astype("int64")
    result["is_policy_category"] = policy_flag
    return result.sort_values(
        ["sex_code", "age_code", "middle_category"]
    ).reset_index(drop=True)


def _validate_grid_demand(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(GRID_DEMAND_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"격자 선호 잠재수요 열이 없습니다: {missing}")
    result = frame[GRID_DEMAND_COLUMNS].copy()
    numeric = [
        "중심점_x",
        "중심점_y",
        "target_population_est",
        "preference_probability_absolute",
        "potential_demand_absolute",
        "other_probability_absolute",
        "other_potential_demand",
        "preference_share_conditional_mnc",
        "reference_year",
    ]
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if len(result) != 484_224 or result["GRID_CD"].nunique() != 60_528:
        raise ValueError(
            "격자 선호 잠재수요 행·격자 수가 다릅니다: "
            f"rows={len(result):,}, grids={result['GRID_CD'].nunique():,}"
        )
    if result.duplicated(["GRID_CD", "middle_category"]).any():
        raise ValueError("격자×선호분류 키가 중복됩니다.")
    if set(result["middle_category"].astype(str)) != set(
        PREFERENCE_OUTPUT_CATEGORIES
    ):
        raise ValueError("격자 선호 잠재수요는 정책 8개 분야여야 합니다.")
    required_numeric = [
        "중심점_x",
        "중심점_y",
        "target_population_est",
        "potential_demand_absolute",
        "other_potential_demand",
    ]
    required_values = result[required_numeric].to_numpy(dtype=float)
    if not np.isfinite(required_values).all():
        raise ValueError(
            "격자 선호 잠재수요 필수 수치열에 결측·무한대가 있습니다."
        )
    nonnegative = [
        "target_population_est",
        "potential_demand_absolute",
        "other_potential_demand",
    ]
    if (result[nonnegative] < 0).any(axis=None):
        raise ValueError("격자 선호 잠재수요에 음수가 있습니다.")
    target_group = result.groupby("GRID_CD")["target_population_est"]
    other_group = result.groupby("GRID_CD")["other_potential_demand"]
    if target_group.nunique().gt(1).any() or other_group.nunique().gt(1).any():
        raise ValueError(
            "같은 격자의 분야별 대상자 또는 기타 잠재수요가 다릅니다."
        )
    target = target_group.first()
    other = other_group.first()
    if not np.isclose(float(target.sum()), 545_692.0, atol=1e-6):
        raise ValueError("격자 선호 잠재수요의 대상자 총량이 다릅니다.")
    policy_total = float(result["potential_demand_absolute"].sum())
    if not np.isclose(
        policy_total + float(other.sum()), float(target.sum()), atol=1e-6
    ):
        raise ValueError(
            "정책 잠재수요와 기타 잠재수요 합이 대상자와 다릅니다."
        )
    positive = result["target_population_est"] > 0
    probabilities = [
        "preference_probability_absolute",
        "other_probability_absolute",
        "preference_share_conditional_mnc",
    ]
    if result.loc[positive, probabilities].isna().any().any():
        raise ValueError("대상자 양수 격자의 선호확률에 결측이 있습니다.")
    if result.loc[~positive, probabilities].notna().any().any():
        raise ValueError("대상자 0명 격자의 선호확률은 무자료여야 합니다.")
    probability_values = result.loc[positive, probabilities].to_numpy(dtype=float)
    if not np.isfinite(probability_values).all() or (
        (probability_values < 0) | (probability_values > 1)
    ).any():
        raise ValueError("격자 선호확률이 0~1 범위를 벗어났습니다.")
    conditional_sums = result.loc[positive].groupby("GRID_CD")[
        "preference_share_conditional_mnc"
    ].sum()
    if not np.allclose(conditional_sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError(
            "대상자 양수 격자의 정책 8개 조건부 구성비 합이 1이 아닙니다."
        )
    if set(result["reference_year"].dropna().astype(int)) != {2024}:
        raise ValueError("격자 선호 잠재수요 기준연도는 2024여야 합니다.")
    result["reference_year"] = result["reference_year"].astype("int64")
    result["is_estimate"] = _coerce_bool(
        result["is_estimate"], context="is_estimate"
    )
    if not result["is_estimate"].all():
        raise ValueError("현재 격자 선호 잠재수요는 모두 추정치여야 합니다.")
    required_text = [
        "GRID_CD",
        "행정동코드",
        "시군구",
        "행정동",
        "middle_category",
    ]
    if result[required_text].isna().any().any():
        raise ValueError(
            "격자 선호 잠재수요의 지역·분류 키에 결측이 있습니다."
        )
    result["행정동코드"] = result["행정동코드"].astype("string").str.zfill(8)
    return result.sort_values(["GRID_CD", "middle_category"]).reset_index(drop=True)


def load_preference_from_local(
    project_root: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """기존 로컬 CSV의 선호확률과 격자 잠재수요를 읽는다."""

    base = Path(project_root) / "data/processed/preference_analysis"
    probability = pd.read_csv(
        base / "model/sex_age_middle_category_preference_2024.csv",
        encoding="utf-8-sig",
    )
    grid = pd.read_csv(
        base / "spatial/grid_middle_category_preference_demand_2024.csv",
        encoding="utf-8-sig",
        dtype={"GRID_CD": "string", "행정동코드": "string"},
        low_memory=False,
    )
    return _validate_probability(probability), _validate_grid_demand(grid)


def _latest_run_id(cursor: Any) -> int:
    cursor.execute(
        """
        SELECT etl_run_id FROM META_ETL_RUN
        WHERE pipeline_name = :pipeline_name AND status = 'SUCCESS'
        ORDER BY etl_run_id DESC FETCH FIRST 1 ROW ONLY
        """,
        pipeline_name=PIPELINE_NAME,
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError("Oracle에 성공한 선호 잠재수요 ETL 실행이 없습니다.")
    return int(row[0])


def load_preference_from_oracle(
    connection: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Oracle 최신 성공 결과를 기존 CSV와 같은 컬럼으로 복원한다."""

    with connection.cursor() as cursor:
        cursor.arraysize = 10_000
        run_id = _latest_run_id(cursor)
        cursor.execute(
            """
            SELECT f.sex_code, f.sex_label, f.age_code, f.age_label,
                   TO_CHAR(f.sex_code) || '_' || TO_CHAR(f.age_code),
                   f.reference_year, c.category_name,
                   f.absolute_probability, f.absolute_probability,
                   f.other_probability, f.conditional_share, f.policy_flag
            FROM FACT_PREF_SEX_AGE f
            JOIN DIM_CATEGORY c
              ON c.scheme_code = f.scheme_code
             AND c.category_code = f.category_code
            WHERE f.etl_run_id = :run_id
            """,
            run_id=run_id,
        )
        probability = pd.DataFrame(cursor.fetchall(), columns=PROBABILITY_COLUMNS)

        cursor.execute(
            """
            SELECT v.grid_cd, v.dong_code, v.district_name, v.dong_name,
                   g.center_x, g.center_y, v.category_name,
                   v.target_population_est, v.absolute_probability,
                   v.potential_demand, v.other_probability,
                   v.other_potential_demand, v.conditional_share,
                   v.reference_year, v.estimate_flag
            FROM VW_GRID_PREF_DEMAND v
            JOIN DIM_GRID g ON g.grid_cd = v.grid_cd
            WHERE v.etl_run_id = :run_id
            """,
            run_id=run_id,
        )
        grid = pd.DataFrame(cursor.fetchall(), columns=GRID_DEMAND_COLUMNS)
    probability["is_policy_category"] = probability[
        "is_policy_category"
    ].eq("Y")
    grid["is_estimate"] = grid["is_estimate"].eq("Y")
    return _validate_probability(probability), _validate_grid_demand(grid)


def load_preference_data(
    *,
    backend: str,
    project_root: str | Path,
    oracle_connection: Any | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """선택한 backend에서 같은 선호확률·격자 잠재수요를 반환한다."""

    normalized = backend.strip().lower()
    if normalized == "local":
        return load_preference_from_local(project_root)
    if normalized == "oracle":
        if oracle_connection is None:
            raise ValueError("oracle backend에는 oracle_connection이 필요합니다.")
        return load_preference_from_oracle(oracle_connection)
    raise ValueError("backend는 local 또는 oracle이어야 합니다.")
