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

from src.data_access import OracleDbSettings
from src.data_access.card_usage import build_category_rows
from src.data_access.merchant import PIPELINE_NAME, load_merchant_for_oracle
from src.data_access.oracle_schema import ensure_merchant_schema


SOURCE_PATH = (
    PROJECT_ROOT
    / "data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx"
)
GRID_LOOKUP_PATH = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"
UPLOAD_RECEIPT = PROJECT_ROOT / ".oci_merchant_upload_receipt.local.json"


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


def _merge_dimensions(cursor: Any, prepared: dict[str, Any]) -> None:
    cursor.executemany(
        """
        MERGE INTO DIM_ADMIN_AREA target
        USING (SELECT :area_code area_code FROM dual) source
        ON (target.area_code = source.area_code)
        WHEN MATCHED THEN UPDATE SET
            target.area_name = :area_name,
            target.area_level = :area_level,
            target.parent_area_code = :parent_area_code,
            target.valid_from = :valid_from,
            target.source_reference_year = :source_reference_year
        WHEN NOT MATCHED THEN INSERT (
            area_code, area_name, area_level, parent_area_code,
            valid_from, source_reference_year
        ) VALUES (
            :area_code, :area_name, :area_level, :parent_area_code,
            :valid_from, :source_reference_year
        )
        """,
        prepared["admin_rows"],
    )
    category_rows, _ = build_category_rows()
    supply_rows = [row for row in category_rows if row["scheme_code"] == "SUPPLY_MID13"]
    cursor.executemany(
        """
        MERGE INTO DIM_CATEGORY target
        USING (
            SELECT :scheme_code scheme_code, :category_code category_code FROM dual
        ) source
        ON (
            target.scheme_code = source.scheme_code
            AND target.category_code = source.category_code
        )
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
        supply_rows,
    )


def _source_file_id(
    cursor: Any,
    object_uri: str,
    source_hash: str,
) -> int:
    cursor.execute(
        "SELECT source_file_id FROM META_SOURCE_FILE WHERE sha256 = :sha256",
        sha256=source_hash,
    )
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            """
            INSERT INTO META_SOURCE_FILE (
                source_name, object_storage_uri, sha256, file_size_bytes,
                reference_year, source_type, sensitivity_level
            ) VALUES (
                :source_name, :object_uri, :sha256, :file_size_bytes,
                2026, 'XLSX', 'INTERNAL'
            )
            """,
            source_name=SOURCE_PATH.name,
            object_uri=object_uri,
            sha256=source_hash,
            file_size_bytes=SOURCE_PATH.stat().st_size,
        )
        cursor.execute(
            "SELECT source_file_id FROM META_SOURCE_FILE WHERE sha256 = :sha256",
            sha256=source_hash,
        )
        row = cursor.fetchone()
    return int(row[0])


def _successful_run_id(cursor: Any, source_file_id: int) -> int | None:
    cursor.execute(
        """
        SELECT MAX(run.etl_run_id)
        FROM META_ETL_RUN run
        JOIN META_ETL_RUN_INPUT input
          ON input.etl_run_id = run.etl_run_id
        WHERE run.pipeline_name = :pipeline_name
          AND run.status = 'SUCCESS'
          AND input.source_file_id = :source_file_id
        """,
        pipeline_name=PIPELINE_NAME,
        source_file_id=source_file_id,
    )
    value = cursor.fetchone()[0]
    return int(value) if value is not None else None


def _start_run(cursor: Any, source_file_id: int) -> int:
    cursor.execute(
        """
        INSERT INTO META_ETL_RUN (pipeline_name, code_version, status)
        VALUES (:pipeline_name, :code_version, 'RUNNING')
        """,
        pipeline_name=PIPELINE_NAME,
        code_version=_git_revision(),
    )
    cursor.execute(
        """
        SELECT MAX(etl_run_id) FROM META_ETL_RUN
        WHERE pipeline_name = :pipeline_name AND status = 'RUNNING'
        """,
        pipeline_name=PIPELINE_NAME,
    )
    run_id = int(cursor.fetchone()[0])
    cursor.execute(
        """
        INSERT INTO META_ETL_RUN_INPUT (etl_run_id, source_file_id, input_role)
        VALUES (:etl_run_id, :source_file_id, 'PRIMARY')
        """,
        etl_run_id=run_id,
        source_file_id=source_file_id,
    )
    return run_id


def _load_rows(cursor: Any, run_id: int, rows: list[dict[str, Any]]) -> None:
    payload = [dict(row, etl_run_id=run_id) for row in rows]
    cursor.executemany(
        """
        INSERT INTO DIM_MERCHANT_SNAPSHOT (
            snapshot_date, merchant_key, source_row_no, merchant_name,
            merchant_type, category_large, scheme_code, category_code,
            category_small, latitude, longitude, usage_info, discount_yn,
            discount_detail, metro, district_reported, district_from_address,
            district_code, address, modified_at, registered_at, keywords, url,
            registration_actor, service_types, phone_payment_detail,
            service_detail, coordinate_valid, district_mismatch,
            phone_payment_available, visiting_service_available,
            disabled_friendly_available, etl_run_id
        ) VALUES (
            :snapshot_date, :merchant_key, :source_row_no, :merchant_name,
            :merchant_type, :category_large, :scheme_code, :category_code,
            :category_small, :latitude, :longitude, :usage_info, :discount_yn,
            :discount_detail, :metro, :district_reported, :district_from_address,
            :district_code, :address, :modified_at, :registered_at, :keywords, :url,
            :registration_actor, :service_types, :phone_payment_detail,
            :service_detail, :coordinate_valid, :district_mismatch,
            :phone_payment_available, :visiting_service_available,
            :disabled_friendly_available, :etl_run_id
        )
        """,
        payload,
    )


def _validate_database(
    cursor: Any,
    run_id: int,
    prepared: dict[str, Any],
) -> dict[str, int]:
    queries = {
        "analysis_rows": "SELECT COUNT(*) FROM DIM_MERCHANT_SNAPSHOT WHERE etl_run_id = :run_id",
        "district_count": "SELECT COUNT(DISTINCT district_code) FROM DIM_MERCHANT_SNAPSHOT WHERE etl_run_id = :run_id",
        "category_count": "SELECT COUNT(DISTINCT category_code) FROM DIM_MERCHANT_SNAPSHOT WHERE etl_run_id = :run_id",
        "invalid_coordinate_rows": "SELECT COUNT(*) FROM DIM_MERCHANT_SNAPSHOT WHERE etl_run_id = :run_id AND coordinate_valid = 'N'",
        "district_mismatch_rows": "SELECT COUNT(*) FROM DIM_MERCHANT_SNAPSHOT WHERE etl_run_id = :run_id AND district_mismatch = 'Y'",
    }
    values: dict[str, int] = {}
    for name, query in queries.items():
        cursor.execute(query, run_id=run_id)
        values[name] = int(cursor.fetchone()[0])
    quality = prepared["quality"].set_index("check")["value"].to_dict()
    expected = {
        "analysis_rows": int(quality["analysis_merchant_rows"]),
        "district_count": 25,
        "category_count": 13,
        "invalid_coordinate_rows": int(quality["invalid_coordinate_rows"]),
        "district_mismatch_rows": int(quality["district_address_mismatch_rows"]),
    }
    if values != expected:
        raise ValueError(f"가맹점 DB 검증값이 다릅니다: {values} != {expected}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="2026-07-06 오프라인 가맹점 snapshot을 MNC_APP에 적재합니다."
    )
    parser.add_argument("--object-uri")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not UPLOAD_RECEIPT.is_file() and args.object_uri is None:
        print(
            json.dumps(
                {
                    "status": "upload_receipt_missing",
                    "error": "먼저 OCI 08 - Upload merchant raw file을 실행하세요.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    object_uri = args.object_uri
    if object_uri is None:
        receipt = json.loads(UPLOAD_RECEIPT.read_text(encoding="utf-8"))
        object_uri = str(receipt.get("object_uri", ""))

    settings = OracleDbSettings.from_env()
    result: dict[str, object] = {
        "status": "checking",
        "user": settings.user,
        "dsn": settings.dsn,
        "source": str(SOURCE_PATH),
        "object_uri": object_uri,
    }
    errors = settings.validation_errors()
    if errors:
        result.update({"status": "invalid_settings", "errors": errors})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    if settings.user != "MNC_APP":
        result.update({"status": "app_user_required"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    if not str(object_uri).startswith("oci://mnc-raw-private@"):
        result.update({"status": "invalid_object_uri"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        prepared = load_merchant_for_oracle(SOURCE_PATH, GRID_LOOKUP_PATH)
        import oracledb
    except Exception as exc:
        result.update(
            {"status": "source_validation_failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    source_hash = _sha256(SOURCE_PATH)
    quality = prepared["quality"].set_index("check")["value"].to_dict()
    result.update(
        {
            "sha256": source_hash,
            "local_quality": {key: int(value) for key, value in quality.items()},
        }
    )

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
        schema_migration = ensure_merchant_schema(connection)
        with connection.cursor() as cursor:
            _merge_dimensions(cursor, prepared)
            source_file_id = _source_file_id(cursor, str(object_uri), source_hash)
            previous_run_id = _successful_run_id(cursor, source_file_id)
            if previous_run_id is not None and not args.force:
                connection.rollback()
                result.update(
                    {
                        "status": "already_loaded",
                        "existing_etl_run_id": previous_run_id,
                    }
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            run_id = _start_run(cursor, source_file_id)
            _load_rows(cursor, run_id, prepared["merchant_rows"])
            validation = _validate_database(cursor, run_id, prepared)
            cursor.execute(
                """
                UPDATE META_ETL_RUN
                SET status = 'SUCCESS', finished_at = SYSTIMESTAMP,
                    input_row_count = :input_rows,
                    output_row_count = :output_rows,
                    warning_count = :warning_count
                WHERE etl_run_id = :etl_run_id
                """,
                input_rows=int(quality["raw_merchant_rows"]),
                output_rows=int(quality["analysis_merchant_rows"]),
                warning_count=int(quality["invalid_coordinate_rows"])
                + int(quality["district_address_mismatch_rows"]),
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
