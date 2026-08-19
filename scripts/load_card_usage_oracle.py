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
from src.data_access.card_usage import load_card_usage_for_oracle
from src.data_access.oracle_schema import ensure_card_usage_detail_schema


SOURCE_PATH = (
    PROJECT_ROOT / "data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx"
)
GRID_LOOKUP_PATH = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"
UPLOAD_RECEIPT = PROJECT_ROOT / ".oci_card_upload_receipt.local.json"
PIPELINE_NAME = "card_usage_2021_2025_raw27_to_mid13_v2"


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


def _executemany(cursor: Any, sql: str, rows: list[dict[str, Any]]) -> None:
    if rows:
        cursor.executemany(sql, rows)


def _merge_dimensions(cursor: Any, prepared: dict[str, Any]) -> None:
    _executemany(
        cursor,
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
    _executemany(
        cursor,
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
        prepared["category_rows"],
    )
    _executemany(
        cursor,
        """
        MERGE INTO BRIDGE_CATEGORY_MAP target
        USING (
            SELECT
                :from_scheme_code from_scheme_code,
                :from_category_code from_category_code,
                :to_scheme_code to_scheme_code,
                :to_category_code to_category_code
            FROM dual
        ) source
        ON (
            target.from_scheme_code = source.from_scheme_code
            AND target.from_category_code = source.from_category_code
            AND target.to_scheme_code = source.to_scheme_code
            AND target.to_category_code = source.to_category_code
        )
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
    source_path: Path,
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
                source_type, sensitivity_level
            ) VALUES (
                :source_name, :object_uri, :sha256, :file_size_bytes,
                'XLSX', 'INTERNAL'
            )
            """,
            source_name=source_path.name,
            object_uri=object_uri,
            sha256=source_hash,
            file_size_bytes=source_path.stat().st_size,
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


def _load_facts(cursor: Any, run_id: int, prepared: dict[str, Any]) -> None:
    raw_rows = [dict(row, etl_run_id=run_id) for row in prepared["raw_rows"]]
    year_rows = [dict(row, etl_run_id=run_id) for row in prepared["year_rows"]]
    middle_rows = [
        dict(row, etl_run_id=run_id) for row in prepared["middle_rows"]
    ]
    sex_rows = [dict(row, etl_run_id=run_id) for row in prepared["sex_rows"]]
    age_rows = [dict(row, etl_run_id=run_id) for row in prepared["age_rows"]]
    _executemany(
        cursor,
        """
        INSERT INTO STG_CARD_USAGE_RAW27 (
            etl_run_id, reference_year, district_name, source_category_name,
            usage_amount_won, usage_count, source_row_no
        ) VALUES (
            :etl_run_id, :reference_year, :district_name, :source_category_name,
            :usage_amount_won, :usage_count, :source_row_no
        )
        """,
        raw_rows,
    )
    _executemany(
        cursor,
        """
        MERGE INTO FACT_CARD_GU_YEAR target
        USING (
            SELECT :reference_year reference_year, :district_code district_code
            FROM dual
        ) source
        ON (
            target.reference_year = source.reference_year
            AND target.district_code = source.district_code
        )
        WHEN MATCHED THEN UPDATE SET
            target.issued_card_count = :issued_card_count,
            target.user_count = :user_count,
            target.issued_amount_won = :issued_amount_won,
            target.budget_amount_won = :budget_amount_won,
            target.used_amount_won = :used_amount_won,
            target.usage_count = :usage_count,
            target.culture_exp_count = :culture_exp_count,
            target.culture_exp_pct = :culture_exp_pct,
            target.etl_run_id = :etl_run_id,
            target.loaded_at = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (
            reference_year, district_code, issued_card_count, user_count,
            issued_amount_won, budget_amount_won, used_amount_won,
            usage_count, culture_exp_count, culture_exp_pct, etl_run_id
        ) VALUES (
            :reference_year, :district_code, :issued_card_count, :user_count,
            :issued_amount_won, :budget_amount_won, :used_amount_won,
            :usage_count, :culture_exp_count, :culture_exp_pct, :etl_run_id
        )
        """,
        year_rows,
    )
    _executemany(
        cursor,
        """
        MERGE INTO FACT_CARD_GU_CAT target
        USING (
            SELECT
                :reference_year reference_year,
                :district_code district_code,
                :scheme_code scheme_code,
                :category_code category_code
            FROM dual
        ) source
        ON (
            target.reference_year = source.reference_year
            AND target.district_code = source.district_code
            AND target.scheme_code = source.scheme_code
            AND target.category_code = source.category_code
        )
        WHEN MATCHED THEN UPDATE SET
            target.usage_amount_won = :usage_amount_won,
            target.usage_count = :usage_count,
            target.etl_run_id = :etl_run_id,
            target.loaded_at = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (
            reference_year, district_code, scheme_code, category_code,
            usage_amount_won, usage_count, etl_run_id
        ) VALUES (
            :reference_year, :district_code, :scheme_code, :category_code,
            :usage_amount_won, :usage_count, :etl_run_id
        )
        """,
        middle_rows,
    )
    _executemany(
        cursor,
        """
        MERGE INTO FACT_CARD_GU_SEX target
        USING (
            SELECT :reference_year reference_year, :district_code district_code,
                   :sex_code sex_code FROM dual
        ) source
        ON (
            target.reference_year = source.reference_year
            AND target.district_code = source.district_code
            AND target.sex_code = source.sex_code
        )
        WHEN MATCHED THEN UPDATE SET
            target.issued_card_count = :issued_card_count,
            target.used_amount_won = :used_amount_won,
            target.etl_run_id = :etl_run_id,
            target.loaded_at = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (
            reference_year, district_code, sex_code,
            issued_card_count, used_amount_won, etl_run_id
        ) VALUES (
            :reference_year, :district_code, :sex_code,
            :issued_card_count, :used_amount_won, :etl_run_id
        )
        """,
        sex_rows,
    )
    _executemany(
        cursor,
        """
        MERGE INTO FACT_CARD_GU_AGE target
        USING (
            SELECT :reference_year reference_year, :district_code district_code,
                   :age_code age_code FROM dual
        ) source
        ON (
            target.reference_year = source.reference_year
            AND target.district_code = source.district_code
            AND target.age_code = source.age_code
        )
        WHEN MATCHED THEN UPDATE SET
            target.issued_card_count = :issued_card_count,
            target.etl_run_id = :etl_run_id,
            target.loaded_at = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (
            reference_year, district_code, age_code,
            issued_card_count, etl_run_id
        ) VALUES (
            :reference_year, :district_code, :age_code,
            :issued_card_count, :etl_run_id
        )
        """,
        age_rows,
    )


def _validate_database(cursor: Any) -> dict[str, int]:
    queries = {
        "district_rows": "SELECT COUNT(*) FROM DIM_ADMIN_AREA WHERE area_level = 'GU'",
        "raw_category_rows": (
            "SELECT COUNT(*) FROM DIM_CATEGORY WHERE scheme_code = 'CARD_RAW27'"
        ),
        "middle_category_rows": (
            "SELECT COUNT(*) FROM DIM_CATEGORY WHERE scheme_code = 'SUPPLY_MID13'"
        ),
        "bridge_rows": "SELECT COUNT(*) FROM BRIDGE_CATEGORY_MAP",
        "card_year_rows": "SELECT COUNT(*) FROM FACT_CARD_GU_YEAR",
        "card_middle_rows": "SELECT COUNT(*) FROM FACT_CARD_GU_CAT",
        "card_sex_rows": "SELECT COUNT(*) FROM FACT_CARD_GU_SEX",
        "card_age_rows": "SELECT COUNT(*) FROM FACT_CARD_GU_AGE",
    }
    values: dict[str, int] = {}
    for name, query in queries.items():
        cursor.execute(query)
        values[name] = int(cursor.fetchone()[0])
    expected = {
        "district_rows": 25,
        "raw_category_rows": 27,
        "middle_category_rows": 13,
        "bridge_rows": 27,
        "card_year_rows": 125,
        "card_middle_rows": 1_625,
        "card_sex_rows": 250,
        "card_age_rows": 1_375,
    }
    if values != expected:
        raise ValueError(f"DB 적재 행 수가 예상과 다릅니다: {values} != {expected}")
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT y.reference_year, y.district_code
            FROM FACT_CARD_GU_YEAR y
            JOIN FACT_CARD_GU_CAT c
              ON c.reference_year = y.reference_year
             AND c.district_code = y.district_code
            GROUP BY y.reference_year, y.district_code,
                     y.used_amount_won, y.usage_count
            HAVING y.used_amount_won <> SUM(c.usage_amount_won)
                OR y.usage_count <> SUM(c.usage_count)
        )
        """
    )
    mismatch_count = int(cursor.fetchone()[0])
    if mismatch_count:
        raise ValueError(f"DB의 13중분류 합계 불일치가 {mismatch_count}건입니다.")
    values["conservation_mismatch_rows"] = mismatch_count
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="카드 이용 2021~2025 원본을 검증하고 MNC_APP에 적재합니다."
    )
    parser.add_argument(
        "--object-uri",
        help="기본값은 OCI 04가 저장한 로컬 업로드 영수증의 object_uri입니다.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="같은 SHA-256의 성공 이력이 있어도 새 실행으로 다시 적재합니다.",
    )
    args = parser.parse_args()

    object_uri = args.object_uri
    if object_uri is None:
        if not UPLOAD_RECEIPT.is_file():
            print(
                json.dumps(
                    {
                        "status": "upload_receipt_missing",
                        "error": "먼저 OCI 04 - Upload card raw file을 실행하세요.",
                        "expected_receipt": str(UPLOAD_RECEIPT),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
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
        result.update(
            {"status": "app_user_required", "error": "ORACLE_DB_USER=MNC_APP이 필요합니다."}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    if not object_uri.startswith("oci://mnc-raw-private@"):
        result.update(
            {"status": "invalid_object_uri", "error": "원본 전용 bucket URI가 아닙니다."}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        prepared = load_card_usage_for_oracle(SOURCE_PATH, GRID_LOOKUP_PATH)
    except Exception as exc:
        result.update(
            {"status": "source_validation_failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    source_hash = _sha256(SOURCE_PATH)
    result["sha256"] = source_hash
    result["local_quality_checks"] = {
        "passed": int(prepared["quality"]["passed"].sum()),
        "total": int(len(prepared["quality"])),
    }

    try:
        import oracledb
    except ImportError as exc:
        result.update({"status": "missing_dependency", "error": str(exc)})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    database_password = getpass.getpass("MNC_APP 데이터베이스 비밀번호: ")
    wallet_password = getpass.getpass("Wallet 비밀번호: ")
    if not database_password or not wallet_password:
        result.update({"status": "password_missing"})
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
        schema_migration = ensure_card_usage_detail_schema(connection)
        with connection.cursor() as cursor:
            _merge_dimensions(cursor, prepared)
            source_file_id = _source_file_id(
                cursor, SOURCE_PATH, object_uri, source_hash
            )
            previous_run_id = _successful_run_id(cursor, source_file_id)
            if previous_run_id is not None and not args.force:
                connection.rollback()
                result.update(
                    {
                        "status": "already_loaded",
                        "existing_etl_run_id": previous_run_id,
                        "note": "동일 원본의 성공 적재 이력이 있어 중복 적재하지 않았습니다.",
                    }
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            run_id = _start_run(cursor, source_file_id)
            _load_facts(cursor, run_id, prepared)
            validation = _validate_database(cursor)
            cursor.execute(
                """
                UPDATE META_ETL_RUN
                SET status = 'SUCCESS', finished_at = SYSTIMESTAMP,
                    input_row_count = 125, output_row_count = 3375,
                    warning_count = 0
                WHERE etl_run_id = :etl_run_id
                """,
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
