"""문화누리카드 이용실적을 Oracle 적재용 행으로 변환한다."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from notebooks.eda._common import (
    AGE_COLUMNS,
    CATEGORIES,
    MERCHANT_USAGE_CATEGORY_MAP,
    load_usage_data,
)


RAW_SCHEME = "CARD_RAW27"
MIDDLE_SCHEME = "SUPPLY_MID13"

RAW_CATEGORY_CODES = {
    name: f"R{index:02d}" for index, name in enumerate(CATEGORIES, start=1)
}
MIDDLE_CATEGORY_CODES = {
    name: f"M{index:02d}"
    for index, name in enumerate(MERCHANT_USAGE_CATEGORY_MAP, start=1)
}
AGE_COLUMN_CODES = {
    "issued_under_10": "AGE_U10",
    "issued_10s": "AGE_10S",
    "issued_20s": "AGE_20S",
    "issued_30s": "AGE_30S",
    "issued_40s": "AGE_40S",
    "issued_50s": "AGE_50S",
    "issued_60s": "AGE_60S",
    "issued_70s": "AGE_70S",
    "issued_80s": "AGE_80S",
    "issued_90s": "AGE_90S",
    "issued_100_plus": "AGE_100P",
}


def _integer_or_none(value: Any) -> int | None:
    if pd.isna(value):
        return None
    return int(round(float(value)))


def build_admin_area_rows(grid_lookup_path: str | Path) -> list[dict[str, Any]]:
    """격자 lookup에서 서울과 25개 자치구 코드를 중복 없이 만든다."""

    frame = pd.read_csv(
        grid_lookup_path,
        usecols=["시군구", "행정동코드"],
        dtype={"시군구": "string", "행정동코드": "string"},
    )
    frame["district_code"] = (
        frame["행정동코드"].str.replace(r"\.0$", "", regex=True).str.zfill(8).str[:5]
    )
    districts = (
        frame[["district_code", "시군구"]]
        .drop_duplicates()
        .sort_values("district_code")
        .reset_index(drop=True)
    )
    if len(districts) != 25:
        raise ValueError(f"서울 자치구 코드가 25개가 아닙니다: {len(districts)}")
    if districts["district_code"].duplicated().any():
        raise ValueError("하나의 자치구 코드에 여러 자치구명이 연결됩니다.")
    if districts["시군구"].duplicated().any():
        raise ValueError("하나의 자치구명에 여러 자치구 코드가 연결됩니다.")

    rows: list[dict[str, Any]] = [
        {
            "area_code": "11",
            "area_name": "서울특별시",
            "area_level": "SIDO",
            "parent_area_code": None,
            "valid_from": date(2021, 1, 1),
            "source_reference_year": 2024,
        }
    ]
    rows.extend(
        {
            "area_code": row.district_code,
            "area_name": row.시군구,
            "area_level": "GU",
            "parent_area_code": "11",
            "valid_from": date(2021, 1, 1),
            "source_reference_year": 2024,
        }
        for row in districts.itertuples(index=False)
    )
    return rows


def build_category_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """27개 원분류, 13개 중분류와 27→13 bridge 행을 만든다."""

    dimensions: list[dict[str, Any]] = []
    for order, category_name in enumerate(CATEGORIES, start=1):
        dimensions.append(
            {
                "scheme_code": RAW_SCHEME,
                "category_code": RAW_CATEGORY_CODES[category_name],
                "category_name": category_name,
                "display_order": order,
                "supported_flag": "Y",
                "valid_from_year": 2021,
            }
        )
    for order, category_name in enumerate(MERCHANT_USAGE_CATEGORY_MAP, start=1):
        dimensions.append(
            {
                "scheme_code": MIDDLE_SCHEME,
                "category_code": MIDDLE_CATEGORY_CODES[category_name],
                "category_name": category_name,
                "display_order": order,
                "supported_flag": "Y",
                "valid_from_year": 2021,
            }
        )

    bridges: list[dict[str, Any]] = []
    for middle_name, raw_names in MERCHANT_USAGE_CATEGORY_MAP.items():
        for raw_name in raw_names:
            bridges.append(
                {
                    "from_scheme_code": RAW_SCHEME,
                    "from_category_code": RAW_CATEGORY_CODES[raw_name],
                    "to_scheme_code": MIDDLE_SCHEME,
                    "to_category_code": MIDDLE_CATEGORY_CODES[middle_name],
                    "mapping_weight": 1,
                    "mapping_status": "DIRECT",
                    "mapping_note": f"{raw_name} → {middle_name}",
                }
            )
    if len(bridges) != 27:
        raise ValueError(f"27→13 분류 bridge가 27행이 아닙니다: {len(bridges)}")
    return dimensions, bridges


def build_card_rows(
    usage: pd.DataFrame,
    district_code_by_name: dict[str, str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """검증된 wide 이용자료를 raw27·자치구연도·13중분류 행으로 변환한다."""

    missing_districts = sorted(set(usage["district"]) - set(district_code_by_name))
    if missing_districts:
        raise ValueError(f"자치구 코드가 없는 이용자료 행: {missing_districts}")

    raw_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    middle_rows: list[dict[str, Any]] = []
    sex_rows: list[dict[str, Any]] = []
    age_rows: list[dict[str, Any]] = []
    for source_row_no, row in enumerate(usage.itertuples(index=False), start=1):
        values = row._asdict()
        year = int(values["year"])
        district_name = str(values["district"])
        district_code = district_code_by_name[district_name]
        year_rows.append(
            {
                "reference_year": year,
                "district_code": district_code,
                "issued_card_count": _integer_or_none(values["issued_cards"]),
                "user_count": _integer_or_none(values["users"]),
                "issued_amount_won": _integer_or_none(values["issued_amount_won"]),
                "budget_amount_won": _integer_or_none(values["budget_won"]),
                "used_amount_won": _integer_or_none(values["used_amount_won"]),
                "usage_count": _integer_or_none(values["transactions"]),
                "culture_exp_count": _integer_or_none(
                    values["culture_experience_transactions"]
                ),
                "culture_exp_pct": float(
                    values["culture_experience_transaction_pct"]
                ),
            }
        )
        sex_rows.extend(
            [
                {
                    "reference_year": year,
                    "district_code": district_code,
                    "sex_code": "M",
                    "issued_card_count": _integer_or_none(values["issued_male"]),
                    "used_amount_won": _integer_or_none(values["used_amount_male_won"]),
                },
                {
                    "reference_year": year,
                    "district_code": district_code,
                    "sex_code": "F",
                    "issued_card_count": _integer_or_none(values["issued_female"]),
                    "used_amount_won": _integer_or_none(values["used_amount_female_won"]),
                },
            ]
        )
        age_rows.extend(
            {
                "reference_year": year,
                "district_code": district_code,
                "age_code": AGE_COLUMN_CODES[column_name],
                "issued_card_count": _integer_or_none(values[column_name]),
            }
            for column_name in AGE_COLUMNS
        )
        for raw_name in CATEGORIES:
            raw_rows.append(
                {
                    "reference_year": year,
                    "district_name": district_name,
                    "source_category_name": raw_name,
                    "usage_amount_won": _integer_or_none(values[f"amount_{raw_name}"]),
                    "usage_count": _integer_or_none(values[f"count_{raw_name}"]),
                    "source_row_no": source_row_no,
                }
            )
        for middle_name, raw_names in MERCHANT_USAGE_CATEGORY_MAP.items():
            middle_rows.append(
                {
                    "reference_year": year,
                    "district_code": district_code,
                    "scheme_code": MIDDLE_SCHEME,
                    "category_code": MIDDLE_CATEGORY_CODES[middle_name],
                    "usage_amount_won": sum(
                        _integer_or_none(values[f"amount_{name}"]) or 0
                        for name in raw_names
                    ),
                    "usage_count": sum(
                        _integer_or_none(values[f"count_{name}"]) or 0
                        for name in raw_names
                    ),
                }
            )

    if (
        len(year_rows) != 125
        or len(raw_rows) != 3_375
        or len(middle_rows) != 1_625
        or len(sex_rows) != 250
        or len(age_rows) != 1_375
    ):
        raise ValueError(
            "카드 적재 행 수가 예상과 다릅니다: "
            f"year={len(year_rows)}, raw27={len(raw_rows)}, "
            f"mid13={len(middle_rows)}, sex={len(sex_rows)}, age={len(age_rows)}"
        )
    _validate_conservation(year_rows, raw_rows, middle_rows, district_code_by_name)
    return raw_rows, year_rows, middle_rows, sex_rows, age_rows


def _validate_conservation(
    year_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    middle_rows: list[dict[str, Any]],
    district_code_by_name: dict[str, str],
) -> None:
    name_by_code = {code: name for name, code in district_code_by_name.items()}
    raw = pd.DataFrame(raw_rows)
    middle = pd.DataFrame(middle_rows)
    years = pd.DataFrame(year_rows)
    raw_sum = raw.groupby(["reference_year", "district_name"], as_index=False)[
        ["usage_amount_won", "usage_count"]
    ].sum().rename(
        columns={
            "usage_amount_won": "raw27_amount_won",
            "usage_count": "raw27_count",
        }
    )
    middle["district_name"] = middle["district_code"].map(name_by_code)
    middle_sum = middle.groupby(
        ["reference_year", "district_name"], as_index=False
    )[["usage_amount_won", "usage_count"]].sum().rename(
        columns={
            "usage_amount_won": "mid13_amount_won",
            "usage_count": "mid13_count",
        }
    )
    years["district_name"] = years["district_code"].map(name_by_code)
    expected = years[
        ["reference_year", "district_name", "used_amount_won", "usage_count"]
    ]
    checked = expected.merge(
        raw_sum,
        on=["reference_year", "district_name"],
        validate="1:1",
    ).merge(
        middle_sum,
        on=["reference_year", "district_name"],
        validate="1:1",
    )
    amount_raw_error = (
        checked["used_amount_won"] - checked["raw27_amount_won"]
    ).abs().max()
    count_raw_error = (checked["usage_count"] - checked["raw27_count"]).abs().max()
    amount_middle_error = (
        checked["used_amount_won"] - checked["mid13_amount_won"]
    ).abs().max()
    count_middle_error = (checked["usage_count"] - checked["mid13_count"]).abs().max()
    errors = {
        "raw27_amount": int(amount_raw_error),
        "raw27_count": int(count_raw_error),
        "mid13_amount": int(amount_middle_error),
        "mid13_count": int(count_middle_error),
    }
    if any(errors.values()):
        raise ValueError(f"27→13 통합 전후 합계가 보존되지 않습니다: {errors}")


def load_card_usage_for_oracle(
    workbook_path: str | Path,
    grid_lookup_path: str | Path,
) -> dict[str, Any]:
    """원본 파일을 읽고 품질검사와 Oracle 적재 행 생성을 한 번에 수행한다."""

    usage, quality = load_usage_data(workbook_path)
    failed = quality.loc[~quality["passed"]]
    if not failed.empty:
        raise ValueError(
            "카드 이용 원본 품질검사가 실패했습니다: "
            + ", ".join(failed["check"].astype(str).unique())
        )
    admin_rows = build_admin_area_rows(grid_lookup_path)
    district_code_by_name = {
        row["area_name"]: row["area_code"]
        for row in admin_rows
        if row["area_level"] == "GU"
    }
    category_rows, bridge_rows = build_category_rows()
    raw_rows, year_rows, middle_rows, sex_rows, age_rows = build_card_rows(
        usage, district_code_by_name
    )
    return {
        "usage": usage,
        "quality": quality,
        "admin_rows": admin_rows,
        "category_rows": category_rows,
        "bridge_rows": bridge_rows,
        "raw_rows": raw_rows,
        "year_rows": year_rows,
        "middle_rows": middle_rows,
        "sex_rows": sex_rows,
        "age_rows": age_rows,
    }


# ---------------------------------------------------------------------------
# 기존 local/Oracle 조회 호환 계층
# ---------------------------------------------------------------------------

from typing import Any

import numpy as np
import pandas as pd

from notebooks.eda._common import AGE_COLUMNS, CATEGORIES


PIPELINE_NAME = "card_usage_2021_2025_raw27_to_mid13_v2"


def _query_frame(
    cursor: Any,
    query: str,
    columns: list[str],
    **binds: Any,
) -> pd.DataFrame:
    cursor.execute(query, **binds)
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def assemble_usage_frame(
    year_fact: pd.DataFrame,
    sex_fact: pd.DataFrame,
    age_fact: pd.DataFrame,
    raw27: pd.DataFrame,
) -> pd.DataFrame:
    """정규화된 네 테이블을 기존 EDA의 125행 wide 입력으로 결합한다."""

    key = ["year", "district"]
    if year_fact.duplicated(key).any():
        raise ValueError("자치구 연도별 카드 이용 테이블에 중복 키가 있습니다.")

    sex = sex_fact.pivot(
        index=key,
        columns="sex_code",
        values=["issued_card_count", "used_amount_won"],
    )
    required_sex = {
        ("issued_card_count", "M"),
        ("issued_card_count", "F"),
        ("used_amount_won", "M"),
        ("used_amount_won", "F"),
    }
    if not required_sex.issubset(set(sex.columns)):
        raise ValueError("Oracle 성별 카드 이용 테이블에 M/F 값이 모두 없습니다.")
    sex_column_names = {
        ("issued_card_count", "M"): "issued_male",
        ("issued_card_count", "F"): "issued_female",
        ("used_amount_won", "M"): "used_amount_male_won",
        ("used_amount_won", "F"): "used_amount_female_won",
    }
    sex.columns = [sex_column_names[column] for column in sex.columns]
    sex = sex.reset_index()

    age = age_fact.pivot(
        index=key,
        columns="age_code",
        values="issued_card_count",
    ).rename(columns={code: column for column, code in AGE_COLUMN_CODES.items()})
    missing_ages = sorted(set(AGE_COLUMNS) - set(age.columns))
    if missing_ages:
        raise ValueError(f"Oracle 연령별 발급 테이블에 누락된 구간이 있습니다: {missing_ages}")
    age = age.reset_index()

    amount = raw27.pivot(
        index=key,
        columns="source_category_name",
        values="usage_amount_won",
    ).rename(columns={category: f"amount_{category}" for category in CATEGORIES})
    count = raw27.pivot(
        index=key,
        columns="source_category_name",
        values="usage_count",
    ).rename(columns={category: f"count_{category}" for category in CATEGORIES})
    missing_amount = sorted(
        {f"amount_{category}" for category in CATEGORIES} - set(amount.columns)
    )
    missing_count = sorted(
        {f"count_{category}" for category in CATEGORIES} - set(count.columns)
    )
    if missing_amount or missing_count:
        raise ValueError(
            "Oracle 원본 27분류 staging에 누락된 분류가 있습니다: "
            f"amount={missing_amount}, count={missing_count}"
        )

    usage = (
        year_fact.merge(sex, on=key, validate="1:1")
        .merge(age, on=key, validate="1:1")
        .merge(amount.reset_index(), on=key, validate="1:1")
        .merge(count.reset_index(), on=key, validate="1:1")
    )
    numeric_columns = [column for column in usage if column not in key]
    usage[numeric_columns] = usage[numeric_columns].apply(
        pd.to_numeric, errors="raise"
    )
    # 원본 XLSX가 제공하는 두 소진율은 소수 둘째 자리까지 공표되어 있다.
    # 기존 EDA 입력과 동일하게 복원하되, 원금액·건수 열은 반올림하지 않는다.
    usage["budget_utilization_pct"] = (
        usage["used_amount_won"] / usage["budget_won"] * 100
    ).round(2)
    usage["issued_utilization_pct"] = (
        usage["used_amount_won"] / usage["issued_amount_won"] * 100
    ).round(2)
    usage["user_rate_pct"] = usage["users"] / usage["issued_cards"] * 100
    usage["used_per_issued_won"] = (
        usage["used_amount_won"] / usage["issued_cards"]
    )
    usage["used_per_user_won"] = usage["used_amount_won"] / usage["users"]
    usage["transactions_per_issued"] = (
        usage["transactions"] / usage["issued_cards"]
    )
    usage["average_transaction_won"] = (
        usage["used_amount_won"] / usage["transactions"]
    )
    usage["female_issued_share_pct"] = (
        usage["issued_female"] / usage["issued_cards"] * 100
    )
    senior_columns = [
        "issued_60s",
        "issued_70s",
        "issued_80s",
        "issued_90s",
        "issued_100_plus",
    ]
    usage["senior_60_plus_share_pct"] = (
        usage[senior_columns].sum(axis=1) / usage["issued_cards"] * 100
    )
    return usage.sort_values(key).reset_index(drop=True)


def validate_oracle_usage_frame(usage: pd.DataFrame) -> pd.DataFrame:
    """로컬 원본 없이 Oracle 조회결과 자체의 핵심 보존식을 검사한다."""

    checks: list[dict[str, object]] = []
    for year, group in usage.groupby("year"):
        amount_sum = group[[f"amount_{category}" for category in CATEGORIES]].sum(
            axis=1
        )
        count_sum = group[[f"count_{category}" for category in CATEGORIES]].sum(
            axis=1
        )
        sex_count_sum = group["issued_male"] + group["issued_female"]
        sex_amount_sum = (
            group["used_amount_male_won"] + group["used_amount_female_won"]
        )
        age_sum = group[list(AGE_COLUMNS)].sum(axis=1)
        year_checks = (
            (
                "district_count_is_25",
                group["district"].nunique() == 25,
                float(group["district"].nunique()),
            ),
            (
                "category_amount_sum",
                bool(np.allclose(group["used_amount_won"], amount_sum, atol=0)),
                float((group["used_amount_won"] - amount_sum).abs().max()),
            ),
            (
                "category_count_sum",
                bool(np.allclose(group["transactions"], count_sum, atol=0)),
                float((group["transactions"] - count_sum).abs().max()),
            ),
            (
                "issued_sex_sum",
                bool(np.allclose(group["issued_cards"], sex_count_sum, atol=0)),
                float((group["issued_cards"] - sex_count_sum).abs().max()),
            ),
            (
                "used_sex_amount_sum",
                bool(np.allclose(group["used_amount_won"], sex_amount_sum, atol=0)),
                float((group["used_amount_won"] - sex_amount_sum).abs().max()),
            ),
            (
                "issued_age_sum",
                bool(np.allclose(group["issued_cards"], age_sum, atol=0)),
                float((group["issued_cards"] - age_sum).abs().max()),
            ),
        )
        checks.extend(
            {
                "year": int(year),
                "check": name,
                "passed": passed,
                "value": value,
                "detail": "Oracle 정규화 테이블 자체 보존식 검사",
            }
            for name, passed, value in year_checks
        )
    duplicate_count = int(usage.duplicated(["year", "district"]).sum())
    checks.append(
        {
            "year": 0,
            "check": "year_district_duplicate_key",
            "passed": duplicate_count == 0,
            "value": float(duplicate_count),
            "detail": "Oracle EDA 입력의 연도×자치구 중복 키",
        }
    )
    return pd.DataFrame(checks)


def load_usage_data_from_oracle(connection: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    """MNC_APP 연결에서 기존 EDA와 동일한 카드 이용 DataFrame을 조회한다."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT MAX(etl_run_id) FROM META_ETL_RUN
            WHERE pipeline_name = :pipeline_name AND status = 'SUCCESS'
            """,
            pipeline_name=PIPELINE_NAME,
        )
        value = cursor.fetchone()[0]
        if value is None:
            raise ValueError("Oracle에 성공한 카드 이용 v2 ETL 실행이 없습니다.")
        run_id = int(value)

        year_fact = _query_frame(
            cursor,
            """
            SELECT y.reference_year, a.area_name,
                   y.budget_amount_won, y.issued_card_count, y.user_count,
                   y.issued_amount_won, y.used_amount_won, y.usage_count,
                   y.culture_exp_count, y.culture_exp_pct
            FROM FACT_CARD_GU_YEAR y
            JOIN DIM_ADMIN_AREA a ON a.area_code = y.district_code
            """,
            [
                "year",
                "district",
                "budget_won",
                "issued_cards",
                "users",
                "issued_amount_won",
                "used_amount_won",
                "transactions",
                "culture_experience_transactions",
                "culture_experience_transaction_pct",
            ],
        )
        sex_fact = _query_frame(
            cursor,
            """
            SELECT s.reference_year, a.area_name, s.sex_code,
                   s.issued_card_count, s.used_amount_won
            FROM FACT_CARD_GU_SEX s
            JOIN DIM_ADMIN_AREA a ON a.area_code = s.district_code
            """,
            [
                "year",
                "district",
                "sex_code",
                "issued_card_count",
                "used_amount_won",
            ],
        )
        age_fact = _query_frame(
            cursor,
            """
            SELECT g.reference_year, a.area_name, g.age_code, g.issued_card_count
            FROM FACT_CARD_GU_AGE g
            JOIN DIM_ADMIN_AREA a ON a.area_code = g.district_code
            """,
            ["year", "district", "age_code", "issued_card_count"],
        )
        raw27 = _query_frame(
            cursor,
            """
            SELECT reference_year, district_name, source_category_name,
                   usage_amount_won, usage_count
            FROM STG_CARD_USAGE_RAW27
            WHERE etl_run_id = :etl_run_id
            """,
            [
                "year",
                "district",
                "source_category_name",
                "usage_amount_won",
                "usage_count",
            ],
            etl_run_id=run_id,
        )

    usage = assemble_usage_frame(year_fact, sex_fact, age_fact, raw27)
    quality = validate_oracle_usage_frame(usage)
    failed = quality.loc[~quality["passed"]]
    if not failed.empty:
        names = ", ".join(failed["check"].astype(str).unique())
        raise ValueError(f"Oracle 카드 이용 보존식 검사가 실패했습니다: {names}")
    return usage, quality
