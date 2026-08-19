"""기존 H3SFCA baseline_v1 결과를 계산 변경 없이 MNC_APP에 적재한다."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.upload_accessibility_outputs import OUTPUTS
from src.data_access import OracleDbSettings
from src.data_access.accessibility import (
    DEMAND_BASIS,
    METHOD_CODE,
    PIPELINE_NAME,
    iter_frame_records,
    prepare_h3sfca_baseline_for_oracle,
)
from src.data_access.oracle_schema import ensure_accessibility_schema


OUTPUT_BY_KEY = {str(item["key"]): item for item in OUTPUTS}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _read_receipts() -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for item in OUTPUTS:
        key = str(item["key"])
        source = Path(item["source"])
        receipt_path = Path(item["receipt"])
        if not receipt_path.is_file():
            raise FileNotFoundError(f"{key} OCI 업로드 영수증이 없습니다: {receipt_path}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("sha256") != _sha256(source):
            raise ValueError(f"{key} 업로드 이후 로컬 파일이 변경되었습니다.")
        if receipt.get("size_bytes") != source.stat().st_size:
            raise ValueError(f"{key} 업로드 파일 크기가 현재 로컬 파일과 다릅니다.")
        if not str(receipt.get("object_uri", "")).startswith("oci://"):
            raise ValueError(f"{key} Object Storage URI가 올바르지 않습니다.")
        receipts[key] = receipt
    return receipts


def _prepare() -> dict[str, Any]:
    return prepare_h3sfca_baseline_for_oracle(
        grid_accessibility_path=OUTPUT_BY_KEY["grid_accessibility"]["source"],
        facility_ratio_path=OUTPUT_BY_KEY["facility_ratio"]["source"],
        grid_summary_path=OUTPUT_BY_KEY["grid_summary"]["source"],
        dong_summary_path=OUTPUT_BY_KEY["dong_summary"]["source"],
        category_summary_path=OUTPUT_BY_KEY["category_summary"]["source"],
    )


def _source_file_id(
    cursor: Any,
    *,
    key: str,
    source: Path,
    receipt: dict[str, Any],
) -> int:
    cursor.execute(
        "SELECT source_file_id FROM META_SOURCE_FILE WHERE sha256 = :sha256",
        sha256=receipt["sha256"],
    )
    row = cursor.fetchone()
    if row is None:
        source_type = (
            "CSV_ANALYTIC"
            if key in {"grid_accessibility", "facility_ratio"}
            else "CSV_SUMMARY"
        )
        cursor.execute(
            """
            INSERT INTO META_SOURCE_FILE (
                source_name, object_storage_uri, sha256, file_size_bytes,
                reference_year, source_type, sensitivity_level
            ) VALUES (
                :source_name, :object_uri, :sha256, :file_size_bytes,
                2024, :source_type, 'INTERNAL_AGGREGATE'
            )
            """,
            source_name=source.name,
            object_uri=receipt["object_uri"],
            sha256=receipt["sha256"],
            file_size_bytes=source.stat().st_size,
            source_type=source_type,
        )
        cursor.execute(
            "SELECT source_file_id FROM META_SOURCE_FILE WHERE sha256 = :sha256",
            sha256=receipt["sha256"],
        )
        row = cursor.fetchone()
    return int(row[0])


def _successful_run_id(cursor: Any, source_ids: dict[str, int]) -> int | None:
    bind_names = [f"source_{index}" for index in range(len(source_ids))]
    placeholders = ", ".join(f":{name}" for name in bind_names)
    binds = {name: value for name, value in zip(bind_names, source_ids.values())}
    cursor.execute(
        f"""
        SELECT run.etl_run_id
        FROM META_ETL_RUN run
        JOIN META_ETL_RUN_INPUT input ON input.etl_run_id = run.etl_run_id
        WHERE run.pipeline_name = :pipeline_name
          AND run.status = 'SUCCESS'
          AND input.source_file_id IN ({placeholders})
        GROUP BY run.etl_run_id
        HAVING COUNT(DISTINCT input.source_file_id) = :source_count
        ORDER BY run.etl_run_id DESC
        FETCH FIRST 1 ROW ONLY
        """,
        pipeline_name=PIPELINE_NAME,
        source_count=len(source_ids),
        **binds,
    )
    row = cursor.fetchone()
    return int(row[0]) if row is not None else None


def _start_run(cursor: Any, source_ids: dict[str, int]) -> int:
    run_id_var = cursor.var(int)
    cursor.execute(
        """
        INSERT INTO META_ETL_RUN (pipeline_name, code_version, status)
        VALUES (:pipeline_name, :code_version, 'RUNNING')
        RETURNING etl_run_id INTO :run_id
        """,
        pipeline_name=PIPELINE_NAME,
        code_version=_git_revision(),
        run_id=run_id_var,
    )
    value = run_id_var.getvalue()
    run_id = int(value[0] if isinstance(value, list) else value)
    cursor.executemany(
        """
        INSERT INTO META_ETL_RUN_INPUT (etl_run_id, source_file_id, input_role)
        VALUES (:etl_run_id, :source_file_id, :input_role)
        """,
        [
            {
                "etl_run_id": run_id,
                "source_file_id": source_id,
                "input_role": key.upper(),
            }
            for key, source_id in source_ids.items()
        ],
    )
    return run_id


def _validate_category_codes(cursor: Any, prepared: dict[str, Any]) -> None:
    required = set(prepared["grid"]["category_code"])
    cursor.execute(
        "SELECT category_code FROM DIM_CATEGORY WHERE scheme_code = 'SUPPLY_MID13'"
    )
    existing = {str(row[0]) for row in cursor.fetchall()}
    missing = sorted(required - existing)
    if missing:
        raise ValueError(f"H3SFCA 적재에 필요한 공급 중분류가 DB에 없습니다: {missing}")


def _load_grid(cursor: Any, run_id: int, prepared: dict[str, Any]) -> None:
    statement = """
        INSERT INTO FACT_GRID_ACCESSIBILITY (
            etl_run_id, target_reference_year, merchant_snapshot_date,
            method_code, demand_basis, access_mode_code, grid_cd,
            scheme_code, category_code, accessibility_score,
            accessible_merchant_count, target_population_est
        ) VALUES (
            :etl_run_id, :target_reference_year, :merchant_snapshot_date,
            :method_code, :demand_basis, :access_mode_code, :grid_cd,
            :scheme_code, :category_code, :accessibility_score,
            :accessible_merchant_count, :target_population_est
        )
    """
    total = len(prepared["grid"])
    loaded = 0
    for payload in iter_frame_records(prepared["grid"], etl_run_id=run_id):
        cursor.executemany(statement, payload)
        loaded += len(payload)
        if loaded == total or loaded % 100_000 == 0:
            print(f"[DB 적재 진행] 격자 접근성 {loaded:,}/{total:,}", flush=True)


def _load_facility(cursor: Any, run_id: int, prepared: dict[str, Any]) -> None:
    statement = """
        INSERT INTO FACT_FACILITY_ACCESS_RATIO (
            etl_run_id, target_reference_year, merchant_snapshot_date,
            method_code, demand_basis, access_mode_code, merchant_source_id,
            scheme_code, category_code, effective_demand, facility_name,
            district_name, subcategory_name, supply_quantity,
            supply_demand_ratio
        ) VALUES (
            :etl_run_id, :target_reference_year, :merchant_snapshot_date,
            :method_code, :demand_basis, :access_mode_code, :merchant_source_id,
            :scheme_code, :category_code, :effective_demand, :facility_name,
            :district_name, :subcategory_name, :supply_quantity,
            :supply_demand_ratio
        )
    """
    for payload in iter_frame_records(
        prepared["facility"], etl_run_id=run_id, chunk_size=5_000
    ):
        cursor.executemany(statement, payload)


def _validate_database(cursor: Any, run_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT grid_cd),
               COUNT(DISTINCT category_code), COUNT(DISTINCT access_mode_code),
               SUM(CASE WHEN accessibility_score < 0
                         OR accessible_merchant_count < 0
                         OR target_population_est < 0 THEN 1 ELSE 0 END),
               COUNT(DISTINCT method_code), COUNT(DISTINCT demand_basis)
        FROM FACT_GRID_ACCESSIBILITY WHERE etl_run_id = :run_id
        """,
        run_id=run_id,
    )
    (
        grid_rows,
        grid_count,
        category_count,
        mode_count,
        negative_grid_rows,
        method_count,
        demand_basis_count,
    ) = map(int, cursor.fetchone())
    cursor.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT merchant_source_id),
               SUM(CASE WHEN effective_demand < 0 OR supply_quantity < 0
                         OR supply_demand_ratio < 0 THEN 1 ELSE 0 END)
        FROM FACT_FACILITY_ACCESS_RATIO WHERE etl_run_id = :run_id
        """,
        run_id=run_id,
    )
    facility_rows, merchant_count, negative_facility_rows = map(int, cursor.fetchone())
    values = {
        "grid_accessibility_rows": grid_rows,
        "grid_count": grid_count,
        "category_count": category_count,
        "access_mode_count": mode_count,
        "facility_ratio_rows": facility_rows,
        "merchant_count": merchant_count,
        "negative_grid_rows": negative_grid_rows,
        "negative_facility_rows": negative_facility_rows,
        "method_count": method_count,
        "demand_basis_count": demand_basis_count,
        "method_code": METHOD_CODE,
        "demand_basis": DEMAND_BASIS,
    }
    expected = {
        "grid_accessibility_rows": 304_509,
        "grid_count": 56_496,
        "category_count": 10,
        "access_mode_count": 2,
        "facility_ratio_rows": 4_282,
        "merchant_count": 4_282,
        "negative_grid_rows": 0,
        "negative_facility_rows": 0,
        "method_count": 1,
        "demand_basis_count": 1,
    }
    mismatches = {
        key: {"actual": values[key], "expected": expected_value}
        for key, expected_value in expected.items()
        if values[key] != expected_value
    }
    if mismatches:
        raise ValueError(f"H3SFCA DB 적재 검증값이 다릅니다: {mismatches}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

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
        receipts = _read_receipts()
        print("[준비 진행] 기존 H3SFCA 5개 산출물 검증", flush=True)
        prepared = _prepare()
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
    run_id: int | None = None
    try:
        connection = oracledb.connect(
            user=settings.user,
            password=database_password,
            dsn=settings.dsn,
            config_dir=str(settings.wallet_dir),
            wallet_location=str(settings.wallet_dir),
            wallet_password=wallet_password,
        )
        schema_migration = ensure_accessibility_schema(connection)
        with connection.cursor() as cursor:
            _validate_category_codes(cursor, prepared)
            source_ids = {
                key: _source_file_id(
                    cursor,
                    key=key,
                    source=Path(OUTPUT_BY_KEY[key]["source"]),
                    receipt=receipt,
                )
                for key, receipt in receipts.items()
            }
            previous_run_id = _successful_run_id(cursor, source_ids)
            if previous_run_id is not None and not args.force:
                connection.rollback()
                result.update(
                    {"status": "already_loaded", "existing_etl_run_id": previous_run_id}
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0

            run_id = _start_run(cursor, source_ids)
            _load_grid(cursor, run_id, prepared)
            _load_facility(cursor, run_id, prepared)
            validation = _validate_database(cursor, run_id)
            output_rows = len(prepared["grid"]) + len(prepared["facility"])
            cursor.execute(
                """
                UPDATE META_ETL_RUN
                SET status = 'SUCCESS', finished_at = SYSTIMESTAMP,
                    input_row_count = :input_rows,
                    output_row_count = :output_rows,
                    warning_count = 0
                WHERE etl_run_id = :etl_run_id
                """,
                input_rows=output_rows,
                output_rows=output_rows,
                etl_run_id=run_id,
            )
        connection.commit()
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        result.update(
            {
                "status": "database_load_failed",
                "etl_run_id": run_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if connection is not None:
            connection.close()

    result.update(
        {
            "status": "database_load_ok",
            "etl_run_id": run_id,
            "database_validation": validation,
            "schema_migration": schema_migration,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
