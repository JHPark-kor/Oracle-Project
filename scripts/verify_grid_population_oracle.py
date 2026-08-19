"""격자·성연령 대상자의 로컬 계산과 Oracle 적재값을 전 행 검증한다."""

from __future__ import annotations

import getpass
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OracleDbSettings
from src.data_access.grid_population import (
    FACT_COLUMNS,
    PIPELINE_NAME,
    prepare_grid_population_for_oracle,
)
from src.data_access.oracle_validation import compare_keyed_numeric_frames


TARGET_SOURCE = (
    PROJECT_ROOT
    / "analysis_table/data/output/서울시_격자_100m_문화누리대상자_성연령별_인구수.csv"
)
GRID_LOOKUP = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"


def _canonical(value: Any, kind: str) -> bytes:
    if value is None or pd.isna(value):
        return b"<NULL>"
    if kind == "int":
        return str(int(value)).encode("utf-8")
    if kind == "float3":
        return f"{float(value):.3f}".encode("utf-8")
    return str(value).encode("utf-8")


def _digest_rows(rows: Iterable[tuple[Any, ...]], kinds: tuple[str, ...]) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        count += 1
        for value, kind in zip(row, kinds, strict=True):
            encoded = _canonical(value, kind)
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
    return count, digest.hexdigest()


def _stream_cursor_digest(
    cursor: Any,
    kinds: tuple[str, ...],
    *,
    batch_size: int = 10_000,
) -> tuple[int, str]:
    def rows() -> Iterable[tuple[Any, ...]]:
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            yield from batch

    return _digest_rows(rows(), kinds)


def _check(context: str, **values: Any) -> dict[str, Any]:
    passed = all(value is True for key, value in values.items() if key.startswith("ok_"))
    return {"context": context, **values, "passed": passed}


def _progress(step: str) -> None:
    print(f"[검증 진행] {step}", flush=True)


def main() -> int:
    settings = OracleDbSettings.from_env()
    result: dict[str, object] = {"status": "checking", "user": settings.user, "dsn": settings.dsn}
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
        _progress("1/6 로컬 격자·성연령 자료 준비")
        prepared = prepare_grid_population_for_oracle(TARGET_SOURCE, GRID_LOOKUP)
        import oracledb
    except Exception as exc:
        result.update({"status": "local_preparation_failed", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    database_password = getpass.getpass("MNC_APP 데이터베이스 비밀번호: ")
    wallet_password = getpass.getpass("Wallet 비밀번호: ")
    if not database_password or not wallet_password:
        result["status"] = "password_missing"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    fact = prepared["fact"]
    local_sex_age = (
        fact.groupby(["sex_code", "aligned_age_order"], as_index=False)
        .agg(
            row_count=("grid_cd", "size"),
            target_population_est=("target_population_est", "sum"),
        )
    )
    dong_by_grid = {
        str(row["grid_cd"]): str(row["dong_code"])
        for row in prepared["grid_rows"]
    }
    local_dong_cells = fact[
        ["grid_cd", "sex_code", "aligned_age_order", "target_population_est"]
    ].copy()
    local_dong_cells["dong_code"] = local_dong_cells["grid_cd"].map(dong_by_grid)
    local_dong_sex_age = (
        local_dong_cells.groupby(
            ["dong_code", "sex_code", "aligned_age_order"], as_index=False
        )
        .agg(
            row_count=("grid_cd", "size"),
            target_population_est=("target_population_est", "sum"),
        )
    )
    all_grid_codes = sorted(dong_by_grid)
    sample_step = max(1, len(all_grid_codes) // 50)
    sample_grid_codes = all_grid_codes[::sample_step][:50]

    connection = None
    try:
        _progress("2/6 Oracle 연결")
        connection = oracledb.connect(
            user=settings.user,
            password=database_password,
            dsn=settings.dsn,
            config_dir=str(settings.wallet_dir),
            wallet_location=str(settings.wallet_dir),
            wallet_password=wallet_password,
        )
        with connection.cursor() as cursor:
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
                raise ValueError("Oracle에 성공한 격자 대상자 ETL 실행이 없습니다.")
            run_id = int(row[0])

            _progress("3/6 격자 60,528개 위치·행정구역 대조")
            local_grid_rows = sorted(
                (
                    item["grid_cd"], item["dong_code"], item["center_x"],
                    item["center_y"], item["grid_cd_500"],
                    item["source_reference_year"],
                )
                for item in prepared["grid_rows"]
            )
            grid_kinds = ("str", "str", "float3", "float3", "str", "int")
            local_grid_count, local_grid_hash = _digest_rows(local_grid_rows, grid_kinds)
            cursor.execute(
                """
                SELECT grid_cd, dong_code, center_x, center_y,
                       grid_cd_500, source_reference_year
                FROM DIM_GRID ORDER BY grid_cd
                """
            )
            oracle_grid_count, oracle_grid_hash = _stream_cursor_digest(cursor, grid_kinds)

            _progress("4/6 대상자 총량·성연령·행정동 집계 대조")
            cursor.execute(
                """
                SELECT COUNT(*), NVL(SUM(target_population_est), 0),
                       COUNT(DISTINCT grid_cd),
                       SUM(CASE WHEN target_population_est < 0 THEN 1 ELSE 0 END),
                       COUNT(DISTINCT proxy_flag), MIN(proxy_flag),
                       COUNT(DISTINCT overlap_adjusted), MIN(overlap_adjusted)
                FROM FACT_GRID_TARGET_SEX_AGE WHERE etl_run_id = :run_id
                """,
                run_id=run_id,
            )
            (
                aligned_rows,
                aligned_total,
                aligned_grids,
                negative_rows,
                proxy_flag_count,
                proxy_flag,
                overlap_flag_count,
                overlap_adjusted,
            ) = cursor.fetchone()
            aligned_rows = int(aligned_rows)
            aligned_total = int(aligned_total)
            aligned_grids = int(aligned_grids)
            negative_rows = int(negative_rows)

            cursor.execute(
                """
                SELECT sex_code, aligned_age_order, COUNT(*),
                       SUM(target_population_est)
                FROM FACT_GRID_TARGET_SEX_AGE
                WHERE etl_run_id = :run_id
                GROUP BY sex_code, aligned_age_order
                ORDER BY sex_code, aligned_age_order
                """,
                run_id=run_id,
            )
            oracle_sex_age = pd.DataFrame(
                cursor.fetchall(),
                columns=[
                    "sex_code",
                    "aligned_age_order",
                    "row_count",
                    "target_population_est",
                ],
            )
            sex_age_comparison = compare_keyed_numeric_frames(
                local_sex_age,
                oracle_sex_age,
                key_columns=["sex_code", "aligned_age_order"],
                numeric_columns=["row_count", "target_population_est"],
                context="성별×통일연령 18개 셀",
            )

            cursor.execute(
                """
                SELECT g.dong_code, f.sex_code, f.aligned_age_order,
                       COUNT(*), SUM(f.target_population_est)
                FROM FACT_GRID_TARGET_SEX_AGE f
                JOIN DIM_GRID g ON g.grid_cd = f.grid_cd
                WHERE f.etl_run_id = :run_id
                GROUP BY g.dong_code, f.sex_code, f.aligned_age_order
                ORDER BY g.dong_code, f.sex_code, f.aligned_age_order
                """,
                run_id=run_id,
            )
            oracle_dong_sex_age = pd.DataFrame(
                cursor.fetchall(),
                columns=[
                    "dong_code",
                    "sex_code",
                    "aligned_age_order",
                    "row_count",
                    "target_population_est",
                ],
            )
            dong_comparison = compare_keyed_numeric_frames(
                local_dong_sex_age,
                oracle_dong_sex_age,
                key_columns=["dong_code", "sex_code", "aligned_age_order"],
                numeric_columns=["row_count", "target_population_est"],
                context="행정동×성별×통일연령 전체 셀",
            )

            _progress("5/6 대표 격자 50개 원행 전체 열 대조")
            fact_kinds = (
                "int", "str", "int", "str", "int", "str", "int", "str",
                "str", "str", "str", "str", "int", "int", "str", "str", "str",
            )
            local_sample = fact.loc[fact["grid_cd"].isin(sample_grid_codes)]
            local_sample_count, local_sample_hash = _digest_rows(
                local_sample[FACT_COLUMNS].itertuples(index=False, name=None),
                fact_kinds,
            )
            bind_names = ", ".join(
                f":sample_grid_{index}" for index in range(len(sample_grid_codes))
            )
            sample_binds = {
                f"sample_grid_{index}": grid_cd
                for index, grid_cd in enumerate(sample_grid_codes)
            }
            cursor.execute(
                f"""
                SELECT reference_year, grid_cd, sex_code, sex_label,
                       aligned_age_order, aligned_age_group, model_age_code,
                       model_age_label, model_applicable, alignment_status,
                       alignment_note, source_age_groups, source_age_group_count,
                       target_population_est, proxy_flag, overlap_adjusted,
                       estimate_method
                FROM FACT_GRID_TARGET_SEX_AGE
                WHERE etl_run_id = :run_id
                  AND grid_cd IN ({bind_names})
                ORDER BY grid_cd, sex_code, aligned_age_order
                """,
                run_id=run_id,
                **sample_binds,
            )
            oracle_sample_count, oracle_sample_hash = _stream_cursor_digest(
                cursor, fact_kinds
            )

            _progress("6/6 15세 이상 View·행정구역·proxy 표시 확인")
            cursor.execute(
                """
                SELECT COUNT(*), NVL(SUM(target_population_est), 0),
                       COUNT(DISTINCT grid_cd)
                FROM VW_GRID_TARGET_MODEL_INPUT
                """
            )
            model_rows, model_total, model_grids = map(int, cursor.fetchone())
            cursor.execute(
                """
                SELECT
                    SUM(CASE WHEN area_level = 'GU' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN area_level = 'DONG' THEN 1 ELSE 0 END)
                FROM DIM_ADMIN_AREA
                """
            )
            gu_count, dong_count = map(int, cursor.fetchone())
    except Exception as exc:
        result.update({"status": "oracle_read_failed", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if connection is not None:
            connection.close()

    checks = [
        _check(
            "100m 격자 위치·행정구역 전체 행",
            local_rows=local_grid_count,
            oracle_rows=oracle_grid_count,
            ok_row_count=local_grid_count == oracle_grid_count,
            ok_sha256=local_grid_hash == oracle_grid_hash,
        ),
        _check(
            "원본→9개 연령구간 행·총량·키 구조",
            source_total=prepared["source_total"],
            oracle_total=aligned_total,
            ok_total=prepared["source_total"] == aligned_total,
            ok_rows=aligned_rows == len(prepared["fact"]),
            ok_grids=aligned_grids == len(prepared["grid_rows"]),
            ok_no_negative=negative_rows == 0,
        ),
        _check(
            "성연령 및 행정동별 전체 집계",
            sex_age=sex_age_comparison,
            dong_sex_age=dong_comparison,
            ok_sex_age=bool(sex_age_comparison["passed"]),
            ok_dong_sex_age=bool(dong_comparison["passed"]),
        ),
        _check(
            "대표 격자 50개 원행 전체 열",
            local_rows=local_sample_count,
            oracle_rows=oracle_sample_count,
            ok_row_count=local_sample_count == oracle_sample_count,
            ok_sha256=local_sample_hash == oracle_sample_hash,
        ),
        _check(
            "15세 이상 모델 입력·행정구역·proxy 표시",
            local_rows=len(prepared["model_input"]),
            oracle_rows=model_rows,
            local_total=prepared["model_total"],
            oracle_total=model_total,
            ok_rows=model_rows == len(prepared["model_input"]),
            ok_total=model_total == prepared["model_total"],
            ok_grids=model_grids == len(prepared["grid_rows"]),
            gu_count=gu_count,
            dong_count=dong_count,
            proxy_flag=proxy_flag,
            overlap_adjusted=overlap_adjusted,
            ok_gu_count=gu_count == 25,
            ok_dong_count=dong_count == 426,
            ok_proxy_flag=proxy_flag_count == 1 and proxy_flag == "Y",
            ok_overlap_flag=(
                overlap_flag_count == 1 and overlap_adjusted == "N"
            ),
        ),
    ]
    passed = all(bool(check["passed"]) for check in checks)
    result.update(
        {
            "status": "parity_ok" if passed else "parity_failed",
            "etl_run_id": run_id,
            "checks": checks,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
