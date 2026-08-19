"""100m 격자와 성별·연령별 추정 대상자를 MNC_APP에 적재한다."""

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
from src.data_access.grid_population import (
    PIPELINE_NAME,
    iter_fact_records,
    prepare_grid_population_for_oracle,
)
from src.data_access.oracle_schema import ensure_grid_population_schema


TARGET_SOURCE = (
    PROJECT_ROOT
    / "analysis_table/data/output/서울시_격자_100m_문화누리대상자_성연령별_인구수.csv"
)
GRID_LOOKUP = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"
TARGET_RECEIPT = PROJECT_ROOT / ".oci_target_population_upload_receipt.local.json"
GRID_RECEIPT = PROJECT_ROOT / ".oci_grid_lookup_upload_receipt.local.json"


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


def _read_receipt(path: Path, source: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"OCI 업로드 영수증이 없습니다: {path}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    actual_hash = _sha256(source)
    actual_size = source.stat().st_size
    if receipt.get("sha256") != actual_hash or receipt.get("size_bytes") != actual_size:
        raise ValueError(f"업로드 이후 로컬 입력이 변경되었습니다: {source}")
    if not str(receipt.get("object_uri", "")).startswith("oci://"):
        raise ValueError(f"올바른 Object Storage URI가 아닙니다: {path}")
    return receipt


def _merge_admin_areas(cursor: Any, rows: list[dict[str, Any]]) -> None:
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
        rows,
    )


def _merge_grids(cursor: Any, rows: list[dict[str, Any]]) -> None:
    cursor.executemany(
        """
        MERGE INTO DIM_GRID target
        USING (SELECT :grid_cd grid_cd FROM dual) source
        ON (target.grid_cd = source.grid_cd)
        WHEN MATCHED THEN UPDATE SET
            target.dong_code = :dong_code,
            target.center_x = :center_x,
            target.center_y = :center_y,
            target.grid_cd_500 = :grid_cd_500,
            target.source_reference_year = :source_reference_year
        WHEN NOT MATCHED THEN INSERT (
            grid_cd, dong_code, center_x, center_y,
            grid_cd_500, source_reference_year
        ) VALUES (
            :grid_cd, :dong_code, :center_x, :center_y,
            :grid_cd_500, :source_reference_year
        )
        """,
        rows,
    )


def _source_file_id(
    cursor: Any,
    *,
    source: Path,
    receipt: dict[str, Any],
    source_type: str,
    sensitivity_level: str,
) -> int:
    source_hash = str(receipt["sha256"])
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
                2024, :source_type, :sensitivity_level
            )
            """,
            source_name=source.name,
            object_uri=receipt["object_uri"],
            sha256=source_hash,
            file_size_bytes=source.stat().st_size,
            source_type=source_type,
            sensitivity_level=sensitivity_level,
        )
        cursor.execute(
            "SELECT source_file_id FROM META_SOURCE_FILE WHERE sha256 = :sha256",
            sha256=source_hash,
        )
        row = cursor.fetchone()
    return int(row[0])


def _successful_run_id(cursor: Any, source_ids: tuple[int, int]) -> int | None:
    cursor.execute(
        """
        SELECT run.etl_run_id
        FROM META_ETL_RUN run
        JOIN META_ETL_RUN_INPUT input ON input.etl_run_id = run.etl_run_id
        WHERE run.pipeline_name = :pipeline_name
          AND run.status = 'SUCCESS'
        GROUP BY run.etl_run_id
        HAVING COUNT(*) = 2
           AND SUM(
               CASE WHEN input.source_file_id IN (:source_1, :source_2)
                    THEN 1 ELSE 0 END
           ) = 2
        ORDER BY run.etl_run_id DESC
        FETCH FIRST 1 ROW ONLY
        """,
        pipeline_name=PIPELINE_NAME,
        source_1=source_ids[0],
        source_2=source_ids[1],
    )
    row = cursor.fetchone()
    return int(row[0]) if row is not None else None


def _start_run(cursor: Any, source_ids: tuple[int, int]) -> int:
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
            {"etl_run_id": run_id, "source_file_id": source_ids[0], "input_role": "PRIMARY"},
            {"etl_run_id": run_id, "source_file_id": source_ids[1], "input_role": "GRID_LOOKUP"},
        ],
    )
    return run_id


def _load_fact(cursor: Any, run_id: int, prepared: dict[str, Any]) -> None:
    statement = """
        INSERT INTO FACT_GRID_TARGET_SEX_AGE (
            etl_run_id, reference_year, grid_cd, sex_code, sex_label,
            aligned_age_order, aligned_age_group, model_age_code,
            model_age_label, model_applicable, alignment_status,
            alignment_note, source_age_groups, source_age_group_count,
            target_population_est, proxy_flag, overlap_adjusted, estimate_method
        ) VALUES (
            :etl_run_id, :reference_year, :grid_cd, :sex_code, :sex_label,
            :aligned_age_order, :aligned_age_group, :model_age_code,
            :model_age_label, :model_applicable, :alignment_status,
            :alignment_note, :source_age_groups, :source_age_group_count,
            :target_population_est, :proxy_flag, :overlap_adjusted, :estimate_method
        )
    """
    for payload in iter_fact_records(prepared["fact"], etl_run_id=run_id):
        cursor.executemany(statement, payload)


def _validate_database(
    cursor: Any,
    run_id: int,
    prepared: dict[str, Any],
) -> dict[str, int]:
    queries = {
        "grid_rows": "SELECT COUNT(*) FROM DIM_GRID",
        "dong_count": "SELECT COUNT(*) FROM DIM_ADMIN_AREA WHERE area_level = 'DONG'",
        "aligned_rows": "SELECT COUNT(*) FROM FACT_GRID_TARGET_SEX_AGE WHERE etl_run_id = :run_id",
        "aligned_total": "SELECT SUM(target_population_est) FROM FACT_GRID_TARGET_SEX_AGE WHERE etl_run_id = :run_id",
        "model_rows": "SELECT COUNT(*) FROM FACT_GRID_TARGET_SEX_AGE WHERE etl_run_id = :run_id AND model_applicable = 'Y'",
        "model_total": "SELECT SUM(target_population_est) FROM FACT_GRID_TARGET_SEX_AGE WHERE etl_run_id = :run_id AND model_applicable = 'Y'",
        "negative_rows": "SELECT COUNT(*) FROM FACT_GRID_TARGET_SEX_AGE WHERE etl_run_id = :run_id AND target_population_est < 0",
    }
    values: dict[str, int] = {}
    for name, query in queries.items():
        if ":run_id" in query:
            cursor.execute(query, run_id=run_id)
        else:
            cursor.execute(query)
        values[name] = int(cursor.fetchone()[0] or 0)
    expected = {
        "grid_rows": len(prepared["grid_rows"]),
        "dong_count": 426,
        "aligned_rows": len(prepared["fact"]),
        "aligned_total": prepared["aligned_total"],
        "model_rows": len(prepared["model_input"]),
        "model_total": prepared["model_total"],
        "negative_rows": 0,
    }
    if values != expected:
        raise ValueError(f"격자 대상자 DB 검증값이 다릅니다: {values} != {expected}")
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
    if settings.user != "MNC_APP":
        result["status"] = "app_user_required"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        target_receipt = _read_receipt(TARGET_RECEIPT, TARGET_SOURCE)
        grid_receipt = _read_receipt(GRID_RECEIPT, GRID_LOOKUP)
        prepared = prepare_grid_population_for_oracle(TARGET_SOURCE, GRID_LOOKUP)
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
        schema_migration = ensure_grid_population_schema(connection)
        with connection.cursor() as cursor:
            target_source_id = _source_file_id(
                cursor,
                source=TARGET_SOURCE,
                receipt=target_receipt,
                source_type="CSV_DERIVED_PROXY",
                sensitivity_level="INTERNAL_AGGREGATE",
            )
            grid_source_id = _source_file_id(
                cursor,
                source=GRID_LOOKUP,
                receipt=grid_receipt,
                source_type="CSV_GRID_LOOKUP",
                sensitivity_level="INTERNAL_AGGREGATE",
            )
            source_ids = (target_source_id, grid_source_id)
            previous_run_id = _successful_run_id(cursor, source_ids)
            if previous_run_id is not None and not args.force:
                connection.rollback()
                result.update(
                    {"status": "already_loaded", "existing_etl_run_id": previous_run_id}
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0

            _merge_admin_areas(cursor, prepared["admin_rows"])
            _merge_grids(cursor, prepared["grid_rows"])
            run_id = _start_run(cursor, source_ids)
            _load_fact(cursor, run_id, prepared)
            validation = _validate_database(cursor, run_id, prepared)
            cursor.execute(
                """
                UPDATE META_ETL_RUN
                SET status = 'SUCCESS', finished_at = SYSTIMESTAMP,
                    input_row_count = :input_rows,
                    output_row_count = :output_rows,
                    warning_count = 1
                WHERE etl_run_id = :etl_run_id
                """,
                input_rows=len(prepared["source"]),
                output_rows=len(prepared["fact"]),
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
            "source_population_total": prepared["source_total"],
            "model_population_15plus": prepared["model_total"],
            "proxy_note": "기초·차상위 단순합이며 자격군 간 중복 미조정",
            "database_validation": validation,
            "schema_migration": schema_migration,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
