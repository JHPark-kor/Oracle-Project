"""문화누리카드 오프라인 가맹점 snapshot을 Oracle 적재 행으로 변환한다."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from notebooks.exploratory_eda.kim_sunghyun._common import (
    MERCHANT_USAGE_CATEGORY_MAP,
    load_merchant_data,
)
from src.data_access.card_usage import (
    MIDDLE_CATEGORY_CODES,
    MIDDLE_SCHEME,
    build_admin_area_rows,
)


SNAPSHOT_DATE = date(2026, 7, 6)
PIPELINE_NAME = "merchant_snapshot_2026_07_06_v1"


def merchant_key(merchant_name: str, address: str) -> str:
    """기존 완전중복 기준과 같은 이름·주소 조합의 결정적 키를 만든다."""

    value = f"{merchant_name.strip()}\x1f{address.strip()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nullable_text(value: Any) -> str | None:
    if pd.isna(value):
        return None
    return str(value)


def _nullable_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _nullable_datetime(value: Any) -> datetime | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).to_pydatetime()


def _yn(value: Any) -> str:
    if pd.isna(value):
        raise ValueError("가맹점 품질 flag에 결측값이 있습니다.")
    return "Y" if bool(value) else "N"


def build_merchant_rows(
    analysis: pd.DataFrame,
    district_code_by_name: dict[str, str],
    *,
    snapshot_date: date = SNAPSHOT_DATE,
) -> list[dict[str, Any]]:
    """중복 제거된 EDA 가맹점을 snapshot 테이블 행으로 만든다."""

    expected_categories = set(MERCHANT_USAGE_CATEGORY_MAP)
    actual_categories = set(analysis["category_mid"].dropna().astype(str))
    if actual_categories != expected_categories:
        raise ValueError(
            "가맹점 중분류가 공급 13개와 다릅니다: "
            f"missing={sorted(expected_categories - actual_categories)}, "
            f"extra={sorted(actual_categories - expected_categories)}"
        )
    missing_districts = sorted(set(analysis["district"]) - set(district_code_by_name))
    if missing_districts:
        raise ValueError(f"자치구 코드가 없는 가맹점 행: {missing_districts}")
    if analysis.duplicated(["merchant_name", "address"]).any():
        raise ValueError("분석용 가맹점에 이름·주소 완전중복이 남아 있습니다.")

    rows: list[dict[str, Any]] = []
    for source_row_no, record in enumerate(
        analysis.itertuples(index=False), start=1
    ):
        values = record._asdict()
        category_name = str(values["category_mid"])
        name = str(values["merchant_name"])
        address = str(values["address"])
        district = str(values["district"])
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "merchant_key": merchant_key(name, address),
                "source_row_no": source_row_no,
                "merchant_name": name,
                "merchant_type": _nullable_text(values["merchant_type"]),
                "category_large": _nullable_text(values["category_large"]),
                "scheme_code": MIDDLE_SCHEME,
                "category_code": MIDDLE_CATEGORY_CODES[category_name],
                "category_small": _nullable_text(values["category_small"]),
                "latitude": _nullable_float(values["latitude"]),
                "longitude": _nullable_float(values["longitude"]),
                "usage_info": _nullable_text(values["usage_info"]),
                "discount_yn": _nullable_text(values["discount_yn"]),
                "discount_detail": _nullable_text(values["discount_detail"]),
                "metro": _nullable_text(values["metro"]),
                "district_reported": _nullable_text(values["district_reported"]),
                "district_from_address": _nullable_text(
                    values["district_from_address"]
                ),
                "district_code": district_code_by_name[district],
                "address": address,
                "modified_at": _nullable_datetime(values["modified_at"]),
                "registered_at": _nullable_datetime(values["registered_at"]),
                "keywords": _nullable_text(values["keywords"]),
                "url": _nullable_text(values["url"]),
                "registration_actor": _nullable_text(
                    values["registration_actor"]
                ),
                "service_types": _nullable_text(values["service_types"]),
                "phone_payment_detail": _nullable_text(
                    values["phone_payment_detail"]
                ),
                "service_detail": _nullable_text(values["service_detail"]),
                "coordinate_valid": _yn(values["coordinate_valid"]),
                "district_mismatch": _yn(values["district_mismatch"]),
                "phone_payment_available": _yn(
                    values["phone_payment_available"]
                ),
                "visiting_service_available": _yn(
                    values["visiting_service_available"]
                ),
                "disabled_friendly_available": _yn(
                    values["disabled_friendly_available"]
                ),
            }
        )
    keys = [row["merchant_key"] for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("가맹점 결정적 키가 중복되었습니다.")
    return rows


def load_merchant_for_oracle(
    source_path: str | Path,
    grid_lookup_path: str | Path,
    *,
    snapshot_date: date = SNAPSHOT_DATE,
) -> dict[str, Any]:
    """기존 EDA loader를 재사용해 로컬 검증과 Oracle 행을 함께 만든다."""

    raw, analysis, quality = load_merchant_data(source_path)
    admin_rows = build_admin_area_rows(grid_lookup_path)
    district_code_by_name = {
        str(row["area_name"]): str(row["area_code"])
        for row in admin_rows
        if row["area_level"] == "GU"
    }
    rows = build_merchant_rows(
        analysis,
        district_code_by_name,
        snapshot_date=snapshot_date,
    )
    if len(raw) != 4_727 or len(analysis) != 4_722 or len(rows) != 4_722:
        raise ValueError(
            "현재 가맹점 snapshot의 검증 행 수가 예상과 다릅니다: "
            f"raw={len(raw)}, analysis={len(analysis)}, rows={len(rows)}"
        )
    return {
        "raw": raw,
        "analysis": analysis,
        "quality": quality,
        "admin_rows": admin_rows,
        "merchant_rows": rows,
        "snapshot_date": snapshot_date,
    }


# ---------------------------------------------------------------------------
# 기존 local/Oracle 조회 호환 계층
# ---------------------------------------------------------------------------

from typing import Any

import numpy as np
import pandas as pd



MERCHANT_COLUMNS = [
    "merchant_name",
    "merchant_type",
    "category_large",
    "category_mid",
    "category_small",
    "latitude",
    "longitude",
    "usage_info",
    "discount_yn",
    "discount_detail",
    "metro",
    "district_reported",
    "address",
    "modified_at",
    "registered_at",
    "keywords",
    "url",
    "registration_actor",
    "service_types",
    "phone_payment_detail",
    "service_detail",
    "district_from_address",
    "district_mismatch",
    "district",
    "coordinate_valid",
    "phone_payment_available",
    "visiting_service_available",
    "disabled_friendly_available",
    "exact_duplicate",
]


def _latest_run(cursor: Any) -> tuple[int, int, int]:
    cursor.execute(
        """
        SELECT etl_run_id, input_row_count, output_row_count
        FROM META_ETL_RUN
        WHERE pipeline_name = :pipeline_name AND status = 'SUCCESS'
        ORDER BY etl_run_id DESC
        FETCH FIRST 1 ROW ONLY
        """,
        pipeline_name=PIPELINE_NAME,
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError("Oracle에 성공한 가맹점 snapshot ETL 실행이 없습니다.")
    return int(row[0]), int(row[1]), int(row[2])


def load_merchant_data_from_oracle(
    connection: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """최신 성공 snapshot을 기존 EDA의 4,722행 입력으로 복원한다."""

    with connection.cursor() as cursor:
        run_id, input_rows, output_rows = _latest_run(cursor)
        cursor.execute(
            """
            SELECT
                m.merchant_name, m.merchant_type, m.category_large,
                c.category_name, m.category_small, m.latitude, m.longitude,
                m.usage_info, m.discount_yn, m.discount_detail, m.metro,
                m.district_reported, m.address, m.modified_at, m.registered_at,
                m.keywords, m.url, m.registration_actor, m.service_types,
                m.phone_payment_detail, m.service_detail,
                m.district_from_address, m.district_mismatch,
                a.area_name, m.coordinate_valid, m.phone_payment_available,
                m.visiting_service_available, m.disabled_friendly_available
            FROM DIM_MERCHANT_SNAPSHOT m
            JOIN DIM_CATEGORY c
              ON c.scheme_code = m.scheme_code
             AND c.category_code = m.category_code
            JOIN DIM_ADMIN_AREA a ON a.area_code = m.district_code
            WHERE m.etl_run_id = :etl_run_id
            ORDER BY m.source_row_no
            """,
            etl_run_id=run_id,
        )
        rows = cursor.fetchall()

    columns = [column for column in MERCHANT_COLUMNS if column != "exact_duplicate"]
    analysis = pd.DataFrame(rows, columns=columns)
    if len(analysis) != output_rows:
        raise ValueError(
            "Oracle 가맹점 행 수가 ETL 기록과 다릅니다: "
            f"table={len(analysis)}, metadata={output_rows}"
        )
    for column in ("latitude", "longitude"):
        analysis[column] = pd.to_numeric(analysis[column], errors="coerce")
    for column in ("modified_at", "registered_at"):
        analysis[column] = pd.to_datetime(analysis[column], errors="coerce")
    for column in (
        "district_mismatch",
        "coordinate_valid",
        "phone_payment_available",
        "visiting_service_available",
        "disabled_friendly_available",
    ):
        analysis[column] = analysis[column].eq("Y")
    analysis["exact_duplicate"] = False
    analysis = analysis[MERCHANT_COLUMNS]

    invalid_coordinates = int((~analysis["coordinate_valid"]).sum())
    district_mismatches = int(analysis["district_mismatch"].sum())
    quality = pd.DataFrame(
        [
            {
                "check": "raw_merchant_rows",
                "value": input_rows,
                "detail": "Oracle ETL에 기록된 원본 가맹점 행",
            },
            {
                "check": "exact_duplicate_rows",
                "value": input_rows - output_rows,
                "detail": "원본과 분석행 차이로 확인한 이름·주소 중복행",
            },
            {
                "check": "analysis_merchant_rows",
                "value": len(analysis),
                "detail": "Oracle에서 조회한 분석용 가맹점 행",
            },
            {
                "check": "invalid_coordinate_rows",
                "value": invalid_coordinates,
                "detail": "서울 bounding box 밖, 0 또는 결측 좌표",
            },
            {
                "check": "district_address_mismatch_rows",
                "value": district_mismatches,
                "detail": "신고 자치구와 주소 추출 자치구가 다른 행",
            },
        ]
    )
    return analysis, quality


def compare_merchant_frames(
    local: pd.DataFrame,
    oracle: pd.DataFrame,
) -> dict[str, object]:
    """행 순서·dtype 차이는 허용하고 전체 가맹점 속성값을 비교한다."""

    def keyed(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        result["_merchant_key"] = [
            merchant_key(str(name), str(address))
            for name, address in zip(result["merchant_name"], result["address"])
        ]
        if result["_merchant_key"].duplicated().any():
            raise ValueError("가맹점 비교 키가 중복되었습니다.")
        return result.set_index("_merchant_key").sort_index()

    left = keyed(local)
    right = keyed(oracle)
    missing_from_local = len(right.index.difference(left.index))
    missing_from_oracle = len(left.index.difference(right.index))
    common = left.index.intersection(right.index)
    mismatch_by_column: dict[str, int] = {}
    for column in MERCHANT_COLUMNS:
        left_values = left.loc[common, column]
        right_values = right.loc[common, column]
        if column in {"latitude", "longitude"}:
            equal = np.isclose(
                pd.to_numeric(left_values, errors="coerce"),
                pd.to_numeric(right_values, errors="coerce"),
                rtol=0,
                atol=1e-8,
                equal_nan=True,
            )
        elif column in {"modified_at", "registered_at"}:
            left_dates = pd.to_datetime(left_values)
            right_dates = pd.to_datetime(right_values)
            equal = left_dates.eq(right_dates) | (
                left_dates.isna() & right_dates.isna()
            )
        elif column in {
            "district_mismatch",
            "coordinate_valid",
            "phone_payment_available",
            "visiting_service_available",
            "disabled_friendly_available",
            "exact_duplicate",
        }:
            equal = left_values.astype("boolean").eq(
                right_values.astype("boolean")
            )
        else:
            equal = left_values.astype("string").fillna("<NULL>").eq(
                right_values.astype("string").fillna("<NULL>")
            )
        mismatch_by_column[column] = int((~np.asarray(equal)).sum())
    passed = (
        missing_from_local == 0
        and missing_from_oracle == 0
        and not any(mismatch_by_column.values())
    )
    return {
        "context": "가맹점 EDA 입력 전체 29열",
        "local_rows": len(local),
        "oracle_rows": len(oracle),
        "missing_from_local": missing_from_local,
        "missing_from_oracle": missing_from_oracle,
        "mismatch_by_column": mismatch_by_column,
        "passed": passed,
    }
