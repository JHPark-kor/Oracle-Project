"""선호확률과 100m 격자 잠재수요를 MNC_APP에 정규화 적재한다."""

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

from scripts.upload_preference_outputs import OUTPUTS
from src.data_access import OracleDbSettings
from src.data_access.preference import (
    PIPELINE_NAME,
    PREFERENCE_SCHEME,
    iter_frame_records,
    prepare_preference_for_oracle,
)
from src.data_access.oracle_schema import ensure_preference_schema


OUTPUT_BY_KEY = {str(item["key"]): item for item in OUTPUTS}
PROBABILITY_PATH = Path(OUTPUT_BY_KEY["probability"]["source"])
GRID_DEMAND_PATH = Path(OUTPUT_BY_KEY["grid_demand"]["source"])


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


def _merge_categories_and_bridges(cursor: Any, prepared: dict[str, Any]) -> None:
    cursor.executemany(
        """
        MERGE INTO DIM_CATEGORY target
        USING (
            SELECT :scheme_code scheme_code, :category_code category_code FROM dual
        ) source
        ON (target.scheme_code = source.scheme_code
            AND target.category_code = source.category_code)
        WHEN MATCHED THEN UPDATE SET
            target.category_name = :category_name,
            target.display_order = :display_order,
            target.supported_flag = :supported_flag,
            target.valid_from_year = :valid_from_year
        WHEN NOT MATCHED THEN INSERT (
            scheme_code, category_code, category_name, display_order,
            supported_flag, valid_from_year
        ) VALUES (
            :scheme_code, :category_code, :category_name, :display_order,
            :supported_flag, :valid_from_year
        )
        """,
        prepared["category_rows"],
    )

    required_supply_codes = {
        str(row["to_category_code"]) for row in prepared["bridge_rows"]
    }
    cursor.execute(
        "SELECT category_code FROM DIM_CATEGORY WHERE scheme_code = 'SUPPLY_MID13'"
    )
    existing_supply_codes = {str(row[0]) for row in cursor.fetchall()}
    missing_supply_codes = sorted(required_supply_codes - existing_supply_codes)
    if missing_supply_codes:
        raise ValueError(
            "선호-공급 연결에 필요한 공급 중분류가 DB에 없습니다: "
            f"{missing_supply_codes}"
        )

    cursor.executemany(
        """
        MERGE INTO BRIDGE_CATEGORY_MAP target
        USING (
            SELECT :from_scheme_code from_scheme_code,
                   :from_category_code from_category_code,
                   :to_scheme_code to_scheme_code,
                   :to_category_code to_category_code
            FROM dual
        ) source
        ON (target.from_scheme_code = source.from_scheme_code
            AND target.from_category_code = source.from_category_code
            AND target.to_scheme_code = source.to_scheme_code
            AND target.to_category_code = source.to_category_code)
        WHEN MATCHED THEN UPDATE SET
            target.mapping_weight = :mapping_weight,
            target.mapping_status = :mapping_status,
            target.mapping_note = :mapping_note
        WHEN NOT MATCHED THEN INSERT (
            from_scheme_code, from_category_code,
            to_scheme_code, to_category_code,
            mapping_weight, mapping_status, mapping_note
        ) VALUES (
            :from_scheme_code, :from_category_code,
            :to_scheme_code, :to_category_code,
            :mapping_weight, :mapping_status, :mapping_note
        )
        """,
        prepared["bridge_rows"],
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
        source_type = {
            "model": "MODEL_ARTIFACT",
            "contract": "JSON_CONTRACT",
            "probability": "CSV_STANDARDIZED",
            "grid_demand": "CSV_ANALYTIC",
            "dong_demand": "CSV_ANALYTIC",
            "gu_demand": "CSV_ANALYTIC",
            "validation": "CSV_VALIDATION",
        }[key]
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


def _successful_run_id(
    cursor: Any,
    probability_source_id: int,
    grid_source_id: int,
) -> int | None:
    cursor.execute(
        """
        SELECT run.etl_run_id
        FROM META_ETL_RUN run
        JOIN META_ETL_RUN_INPUT input ON input.etl_run_id = run.etl_run_id
        WHERE run.pipeline_name = :pipeline_name
          AND run.status = 'SUCCESS'
        GROUP BY run.etl_run_id
        HAVING SUM(CASE WHEN input.source_file_id = :probability_id THEN 1 ELSE 0 END) > 0
           AND SUM(CASE WHEN input.source_file_id = :grid_id THEN 1 ELSE 0 END) > 0
        ORDER BY run.etl_run_id DESC
        FETCH FIRST 1 ROW ONLY
        """,
        pipeline_name=PIPELINE_NAME,
        probability_id=probability_source_id,
        grid_id=grid_source_id,
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


def _load_probability(cursor: Any, run_id: int, prepared: dict[str, Any]) -> None:
    statement = """
        INSERT INTO FACT_PREF_SEX_AGE (
            etl_run_id, reference_year, sex_code, sex_label,
            age_code, age_label, scheme_code, category_code,
            absolute_probability, other_probability, conditional_share,
            policy_flag
        ) VALUES (
            :etl_run_id, :reference_year, :sex_code, :sex_label,
            :age_code, :age_label, :scheme_code, :category_code,
            :absolute_probability, :other_probability, :conditional_share,
            :policy_flag
        )
    """
    for payload in iter_frame_records(
        prepared["probability"], etl_run_id=run_id, chunk_size=1_000
    ):
        cursor.executemany(statement, payload)


def _load_grid_demand(cursor: Any, run_id: int, prepared: dict[str, Any]) -> None:
    statement = """
        INSERT INTO FACT_GRID_PREF_DEMAND (
            etl_run_id, reference_year, grid_cd, scheme_code, category_code,
            target_population_est, absolute_probability, potential_demand,
            other_probability, other_potential_demand, conditional_share,
            estimate_flag
        ) VALUES (
            :etl_run_id, :reference_year, :grid_cd, :scheme_code, :category_code,
            :target_population_est, :absolute_probability, :potential_demand,
            :other_probability, :other_potential_demand, :conditional_share,
            :estimate_flag
        )
    """
    total = len(prepared["grid_demand"])
    loaded = 0
    for payload in iter_frame_records(
        prepared["grid_demand"], etl_run_id=run_id, chunk_size=10_000
    ):
        cursor.executemany(statement, payload)
        loaded += len(payload)
        if loaded == total or loaded % 100_000 == 0:
            print(f"[DB 적재 진행] 격자 잠재수요 {loaded:,}/{total:,}", flush=True)


def _validate_database(cursor: Any, run_id: int) -> dict[str, Any]:
    queries = {
        "probability_rows": "SELECT COUNT(*) FROM FACT_PREF_SEX_AGE WHERE etl_run_id = :run_id",
        "probability_category_count": "SELECT COUNT(DISTINCT category_code) FROM FACT_PREF_SEX_AGE WHERE etl_run_id = :run_id",
        "grid_demand_rows": "SELECT COUNT(*) FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id",
        "grid_count": "SELECT COUNT(DISTINCT grid_cd) FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id",
        "grid_category_count": "SELECT COUNT(DISTINCT category_code) FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id",
        "negative_rows": "SELECT COUNT(*) FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id AND (target_population_est < 0 OR potential_demand < 0 OR other_potential_demand < 0)",
        "probability_sum_errors": "SELECT COUNT(*) FROM (SELECT sex_code, age_code FROM FACT_PREF_SEX_AGE WHERE etl_run_id = :run_id GROUP BY sex_code, age_code HAVING ABS(SUM(absolute_probability) - 1) > 0.00000001)",
    }
    values: dict[str, Any] = {}
    for name, query in queries.items():
        cursor.execute(query, run_id=run_id)
        values[name] = int(cursor.fetchone()[0] or 0)

    cursor.execute(
        """
        SELECT
            (SELECT SUM(target_population_est) FROM (
                SELECT grid_cd, MAX(target_population_est) target_population_est
                FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id
                GROUP BY grid_cd
            )),
            (SELECT SUM(potential_demand)
             FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id),
            (SELECT SUM(other_potential_demand) FROM (
                SELECT grid_cd, MAX(other_potential_demand) other_potential_demand
                FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id
                GROUP BY grid_cd
            ))
        FROM dual
        """,
        run_id=run_id,
    )
    target_total, policy_total, other_total = map(float, cursor.fetchone())
    values.update(
        {
            "target_population_15plus": target_total,
            "policy_potential_demand": policy_total,
            "other_potential_demand": other_total,
            "conservation_error": policy_total + other_total - target_total,
        }
    )
    expected = {
        "probability_rows": 126,
        "probability_category_count": 9,
        "grid_demand_rows": 484_224,
        "grid_count": 60_528,
        "grid_category_count": 8,
        "negative_rows": 0,
        "probability_sum_errors": 0,
    }
    mismatches = {
        key: {"actual": values[key], "expected": expected_value}
        for key, expected_value in expected.items()
        if values[key] != expected_value
    }
    if abs(target_total - 545_692.0) > 1e-6:
        mismatches["target_population_15plus"] = {
            "actual": target_total,
            "expected": 545_692.0,
        }
    if abs(values["conservation_error"]) > 1e-6:
        mismatches["conservation_error"] = {
            "actual": values["conservation_error"],
            "expected": 0.0,
        }
    if mismatches:
        raise ValueError(f"선호 DB 적재 검증값이 다릅니다: {mismatches}")
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
    }
    errors = settings.validation_errors()
    if errors:
        result.update({"status": "invalid_settings", "errors": errors})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        receipts = _read_receipts()
        print("[준비 진행] 선호확률·격자 잠재수요 검증", flush=True)
        prepared = prepare_preference_for_oracle(PROBABILITY_PATH, GRID_DEMAND_PATH)
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
        schema_migration = ensure_preference_schema(connection)
        with connection.cursor() as cursor:
            _merge_categories_and_bridges(cursor, prepared)
            source_ids = {
                key: _source_file_id(
                    cursor,
                    key=key,
                    source=Path(OUTPUT_BY_KEY[key]["source"]),
                    receipt=receipt,
                )
                for key, receipt in receipts.items()
            }
            previous_run_id = _successful_run_id(
                cursor,
                source_ids["probability"],
                source_ids["grid_demand"],
            )
            if previous_run_id is not None and not args.force:
                connection.rollback()
                result.update(
                    {"status": "already_loaded", "existing_etl_run_id": previous_run_id}
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0

            run_id = _start_run(cursor, source_ids)
            _load_probability(cursor, run_id, prepared)
            _load_grid_demand(cursor, run_id, prepared)
            validation = _validate_database(cursor, run_id)
            cursor.execute(
                """
                UPDATE META_ETL_RUN
                SET status = 'SUCCESS', finished_at = SYSTIMESTAMP,
                    input_row_count = :input_rows,
                    output_row_count = :output_rows,
                    warning_count = 0
                WHERE etl_run_id = :etl_run_id
                """,
                input_rows=len(prepared["probability"]) + len(prepared["grid_demand"]),
                output_rows=len(prepared["probability"]) + len(prepared["grid_demand"]),
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
            "preference_scheme": PREFERENCE_SCHEME,
            "database_validation": validation,
            "schema_migration": schema_migration,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
