"""기존 H3SFCA 로컬 결과와 Oracle baseline_v1 적재값을 전체 대조한다."""

from __future__ import annotations

import getpass
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.upload_accessibility_outputs import OUTPUTS
from src.data_access import OracleDbSettings
from src.data_access.accessibility import (
    ACCESS_MODE_CODES,
    PIPELINE_NAME,
    prepare_h3sfca_baseline_for_oracle,
)
from src.data_access.card_usage import MIDDLE_CATEGORY_CODES
from src.data_access.oracle_validation import compare_keyed_numeric_frames


OUTPUT_BY_KEY = {str(item["key"]): item for item in OUTPUTS}
GRID_PATH = Path(OUTPUT_BY_KEY["grid_accessibility"]["source"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare() -> dict[str, Any]:
    return prepare_h3sfca_baseline_for_oracle(
        grid_accessibility_path=OUTPUT_BY_KEY["grid_accessibility"]["source"],
        facility_ratio_path=OUTPUT_BY_KEY["facility_ratio"]["source"],
        grid_summary_path=OUTPUT_BY_KEY["grid_summary"]["source"],
        dong_summary_path=OUTPUT_BY_KEY["dong_summary"]["source"],
        category_summary_path=OUTPUT_BY_KEY["category_summary"]["source"],
    )


def _frame(rows: list[tuple[Any, ...]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def _compare_text_frames(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    keys: list[str],
    text_columns: list[str],
    context: str,
) -> dict[str, object]:
    required = keys + text_columns
    for name, frame in (("local", expected), ("oracle", actual)):
        missing = sorted(set(required) - set(frame.columns))
        if missing:
            raise ValueError(f"{context} {name} 필수 열이 없습니다: {missing}")
        if frame.duplicated(keys).any():
            raise ValueError(f"{context} {name} 키가 중복됩니다: {keys}")
    joined = expected[required].merge(
        actual[required],
        on=keys,
        how="outer",
        validate="1:1",
        suffixes=("_local", "_oracle"),
        indicator=True,
    )
    missing_local = int(joined["_merge"].eq("right_only").sum())
    missing_oracle = int(joined["_merge"].eq("left_only").sum())
    mismatch_by_column: dict[str, int] = {}
    mismatch_rows = pd.Series(False, index=joined.index)
    for column in text_columns:
        local = joined[f"{column}_local"].astype("string")
        oracle = joined[f"{column}_oracle"].astype("string")
        mismatch = local.ne(oracle).fillna(local.isna() ^ oracle.isna())
        mismatch_by_column[column] = int(mismatch.sum())
        mismatch_rows |= mismatch
    passed = (
        len(expected) == len(actual)
        and missing_local == 0
        and missing_oracle == 0
        and not mismatch_rows.any()
    )
    return {
        "context": context,
        "local_rows": len(expected),
        "oracle_rows": len(actual),
        "missing_from_local": missing_local,
        "missing_from_oracle": missing_oracle,
        "text_mismatch_rows": int(mismatch_rows.sum()),
        "text_mismatch_by_column": mismatch_by_column,
        "passed": passed,
    }


def _local_grid_labels() -> pd.DataFrame:
    raw = pd.read_csv(GRID_PATH, encoding="utf-8-sig", low_memory=False)
    return pd.DataFrame(
        {
            "access_mode_code": raw["접근수단"].map(ACCESS_MODE_CODES),
            "grid_cd": raw["GRID_CD"].astype("string"),
            "category_code": raw["중분류"].map(MIDDLE_CATEGORY_CODES),
            "district_name": raw["시군구_격자"].astype("string"),
            "dong_name": raw["행정동_격자"].astype("string"),
        }
    )


def _input_hash_check(cursor: Any, run_id: int) -> dict[str, object]:
    expected = {_sha256(Path(item["source"])) for item in OUTPUTS}
    cursor.execute(
        """
        SELECT source.sha256
        FROM META_ETL_RUN_INPUT input
        JOIN META_SOURCE_FILE source
          ON source.source_file_id = input.source_file_id
        WHERE input.etl_run_id = :run_id
        """,
        run_id=run_id,
    )
    actual = {str(row[0]).lower() for row in cursor.fetchall()}
    return {
        "context": "H3SFCA 5개 원본 SHA-256",
        "local_hash_count": len(expected),
        "oracle_hash_count": len(actual),
        "missing_from_oracle": sorted(expected - actual),
        "unexpected_in_oracle": sorted(actual - expected),
        "passed": expected == actual and len(expected) == 5,
    }


def main() -> int:
    settings = OracleDbSettings.from_env()
    result: dict[str, object] = {
        "status": "checking",
        "user": settings.user,
        "dsn": settings.dsn,
        "version": "baseline_v1",
        "calculation_changed": False,
    }
    errors = settings.validation_errors()
    if errors:
        result.update({"status": "invalid_settings", "errors": errors})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        print("[검증 진행] 1/6 기존 H3SFCA 로컬 결과 준비", flush=True)
        prepared = _prepare()
        local_labels = _local_grid_labels()
        import oracledb
    except Exception as exc:
        result.update(
            {"status": "local_preparation_failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    database_password = getpass.getpass("MNC_APP 데이터베이스 비밀번호: ")
    wallet_password = getpass.getpass("Wallet 비밀번호: ")
    if not database_password or not wallet_password:
        result["status"] = "password_missing"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    connection = None
    try:
        print("[검증 진행] 2/6 Oracle 연결", flush=True)
        connection = oracledb.connect(
            user=settings.user,
            password=database_password,
            dsn=settings.dsn,
            config_dir=str(settings.wallet_dir),
            wallet_location=str(settings.wallet_dir),
            wallet_password=wallet_password,
        )
        with connection.cursor() as cursor:
            cursor.arraysize = 10_000
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
                raise ValueError("Oracle에 성공한 H3SFCA baseline_v1 ETL 실행이 없습니다.")
            run_id = int(row[0])

            print("[검증 진행] 3/6 격자 접근성 304,509행 전체 값", flush=True)
            cursor.execute(
                """
                SELECT access_mode_code, grid_cd, category_code,
                       accessibility_score, accessible_merchant_count,
                       target_population_est, district_name, dong_name
                FROM VW_GRID_ACCESSIBILITY
                WHERE etl_run_id = :run_id
                """,
                run_id=run_id,
            )
            oracle_grid = _frame(
                cursor.fetchall(),
                [
                    "access_mode_code",
                    "grid_cd",
                    "category_code",
                    "accessibility_score",
                    "accessible_merchant_count",
                    "target_population_est",
                    "district_name",
                    "dong_name",
                ],
            )
            grid_value_check = compare_keyed_numeric_frames(
                prepared["grid"],
                oracle_grid,
                key_columns=["access_mode_code", "grid_cd", "category_code"],
                numeric_columns=[
                    "accessibility_score",
                    "accessible_merchant_count",
                    "target_population_est",
                ],
                context="기존 H3SFCA 격자 접근성 전체 값",
                absolute_tolerances={
                    "accessibility_score": 1e-12,
                    "accessible_merchant_count": 0,
                    "target_population_est": 1e-9,
                },
            )
            grid_label_check = _compare_text_frames(
                local_labels,
                oracle_grid,
                keys=["access_mode_code", "grid_cd", "category_code"],
                text_columns=["district_name", "dong_name"],
                context="기존 H3SFCA 격자 자치구·행정동",
            )

            print("[검증 진행] 4/6 가맹점 공급수요비 4,282행 전체 값", flush=True)
            cursor.execute(
                """
                SELECT access_mode_code, merchant_source_id, category_code,
                       effective_demand, supply_quantity, supply_demand_ratio,
                       facility_name, district_name, subcategory_name
                FROM FACT_FACILITY_ACCESS_RATIO
                WHERE etl_run_id = :run_id
                """,
                run_id=run_id,
            )
            oracle_facility = _frame(
                cursor.fetchall(),
                [
                    "access_mode_code",
                    "merchant_source_id",
                    "category_code",
                    "effective_demand",
                    "supply_quantity",
                    "supply_demand_ratio",
                    "facility_name",
                    "district_name",
                    "subcategory_name",
                ],
            )
            facility_value_check = compare_keyed_numeric_frames(
                prepared["facility"],
                oracle_facility,
                key_columns=["access_mode_code", "merchant_source_id", "category_code"],
                numeric_columns=["effective_demand", "supply_quantity", "supply_demand_ratio"],
                context="기존 H3SFCA 가맹점 공급수요비 전체 값",
                absolute_tolerances={
                    "effective_demand": 1e-12,
                    "supply_quantity": 1e-12,
                    "supply_demand_ratio": 1e-12,
                },
            )
            facility_text_check = _compare_text_frames(
                prepared["facility"],
                oracle_facility,
                keys=["access_mode_code", "merchant_source_id", "category_code"],
                text_columns=["facility_name", "district_name", "subcategory_name"],
                context="기존 H3SFCA 가맹점 명칭·지역·소분류",
            )

            print("[검증 진행] 5/6 Object Storage 원본 해시", flush=True)
            hash_check = _input_hash_check(cursor, run_id)
            print("[검증 진행] 6/6 기존 요약 CSV 정합성", flush=True)
    except Exception as exc:
        result.update(
            {"status": "oracle_read_failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if connection is not None:
            connection.close()

    checks = [
        grid_value_check,
        grid_label_check,
        facility_value_check,
        facility_text_check,
        hash_check,
        *prepared["summary_checks"],
    ]
    passed = all(bool(check["passed"]) for check in checks)
    result.update(
        {
            "status": "parity_ok" if passed else "parity_failed",
            "etl_run_id": run_id,
            "checks": checks,
            "all_checks_passed": passed,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
