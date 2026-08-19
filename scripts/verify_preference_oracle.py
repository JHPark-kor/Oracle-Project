"""선호확률·격자수요의 로컬 결과와 Oracle 적재·집계값을 검증한다."""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OracleDbSettings
from src.data_access.oracle_validation import compare_keyed_numeric_frames
from src.data_access.preference import (
    PIPELINE_NAME,
    prepare_preference_for_oracle,
)


PROBABILITY_PATH = (
    PROJECT_ROOT
    / "data/processed/preference_analysis/model/"
    "sex_age_middle_category_preference_2024.csv"
)
GRID_DEMAND_PATH = (
    PROJECT_ROOT
    / "data/processed/preference_analysis/spatial/"
    "grid_middle_category_preference_demand_2024.csv"
)
DONG_DEMAND_PATH = (
    PROJECT_ROOT
    / "data/processed/preference_analysis/spatial/"
    "dong_middle_category_preference_demand_2024.csv"
)
GU_DEMAND_PATH = (
    PROJECT_ROOT
    / "data/processed/preference_analysis/spatial/"
    "gu_middle_category_preference_demand_2024.csv"
)

NUMERIC_COLUMNS = [
    "target_population_est",
    "absolute_probability",
    "potential_demand",
    "other_probability",
    "other_potential_demand",
    "conditional_share",
]
TOLERANCES = {column: 1e-8 for column in NUMERIC_COLUMNS}


def _frame(rows: list[tuple[Any, ...]], columns: list[str]) -> pd.DataFrame:
    result = pd.DataFrame(rows, columns=columns)
    for column in NUMERIC_COLUMNS:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _local_region(path: Path, *, level: str) -> pd.DataFrame:
    dtype = {"행정동코드": "string", "자치구코드": "string"}
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=dtype)
    rename = {
        "middle_category": "category_name",
        "preference_probability_absolute": "absolute_probability",
        "potential_demand_absolute": "potential_demand",
        "other_probability_absolute": "other_probability",
        "preference_share_conditional_mnc": "conditional_share",
    }
    frame = frame.rename(columns=rename)
    if level == "dong":
        frame["area_code"] = frame["행정동코드"].str.zfill(8)
    else:
        frame["area_code"] = frame["자치구코드"].str.zfill(5)
    return frame[["area_code", "category_name", *NUMERIC_COLUMNS]]


def _summary_check(cursor: Any, run_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT grid_cd),
               COUNT(DISTINCT category_code),
               SUM(CASE WHEN target_population_est < 0
                          OR potential_demand < 0
                          OR other_potential_demand < 0 THEN 1 ELSE 0 END)
        FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id
        """,
        run_id=run_id,
    )
    rows, grids, categories, negative = map(int, cursor.fetchone())
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
    target, policy, other = map(float, cursor.fetchone())
    passed = (
        rows == 484_224
        and grids == 60_528
        and categories == 8
        and negative == 0
        and abs(target - 545_692.0) <= 1e-6
        and abs(policy + other - target) <= 1e-6
    )
    return {
        "context": "격자 잠재수요 행·키·총량 보존",
        "rows": rows,
        "grid_count": grids,
        "category_count": categories,
        "negative_rows": negative,
        "target_population_15plus": target,
        "policy_potential_demand": policy,
        "other_potential_demand": other,
        "conservation_error": policy + other - target,
        "passed": passed,
    }


def main() -> int:
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
        print("[검증 진행] 1/6 로컬 선호 결과 준비", flush=True)
        prepared = prepare_preference_for_oracle(PROBABILITY_PATH, GRID_DEMAND_PATH)
        local_dong = _local_region(DONG_DEMAND_PATH, level="dong")
        local_gu = _local_region(GU_DEMAND_PATH, level="gu")
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
            run_id = int(row[0])

            print("[검증 진행] 3/6 성별×연령별 선호확률 126행", flush=True)
            cursor.execute(
                """
                SELECT sex_code, age_code, category_code,
                       absolute_probability, other_probability,
                       conditional_share
                FROM FACT_PREF_SEX_AGE
                WHERE etl_run_id = :run_id
                """,
                run_id=run_id,
            )
            oracle_probability = _frame(
                cursor.fetchall(),
                [
                    "sex_code",
                    "age_code",
                    "category_code",
                    "absolute_probability",
                    "other_probability",
                    "conditional_share",
                ],
            )
            probability_check = compare_keyed_numeric_frames(
                prepared["probability"],
                oracle_probability,
                key_columns=["sex_code", "age_code", "category_code"],
                numeric_columns=[
                    "absolute_probability",
                    "other_probability",
                    "conditional_share",
                ],
                context="성별×연령별 선호확률 126행",
                absolute_tolerances={
                    "absolute_probability": 1e-12,
                    "other_probability": 1e-12,
                    "conditional_share": 1e-12,
                },
            )

            print("[검증 진행] 4/6 대표 격자 50개", flush=True)
            all_grids = sorted(prepared["grid_demand"]["grid_cd"].unique())
            sample_step = max(1, len(all_grids) // 50)
            sample_grids = all_grids[::sample_step][:50]
            binds = {f"g{index}": grid for index, grid in enumerate(sample_grids)}
            placeholders = ", ".join(f":g{index}" for index in range(len(sample_grids)))
            cursor.execute(
                f"""
                SELECT grid_cd, category_code, target_population_est,
                       absolute_probability, potential_demand,
                       other_probability, other_potential_demand,
                       conditional_share
                FROM FACT_GRID_PREF_DEMAND
                WHERE etl_run_id = :run_id
                  AND grid_cd IN ({placeholders})
                """,
                run_id=run_id,
                **binds,
            )
            oracle_sample = _frame(
                cursor.fetchall(),
                ["grid_cd", "category_code", *NUMERIC_COLUMNS],
            )
            local_sample = prepared["grid_demand"].loc[
                prepared["grid_demand"]["grid_cd"].isin(sample_grids)
            ]
            grid_sample_check = compare_keyed_numeric_frames(
                local_sample,
                oracle_sample,
                key_columns=["grid_cd", "category_code"],
                numeric_columns=NUMERIC_COLUMNS,
                context="대표 격자 50개×정책 8개",
                absolute_tolerances=TOLERANCES,
            )

            print("[검증 진행] 5/6 행정동·자치구 집계", flush=True)
            region_checks = []
            for view_name, local, context in (
                ("VW_DONG_PREF_DEMAND", local_dong, "행정동 426개×정책 8개"),
                ("VW_GU_PREF_DEMAND", local_gu, "자치구 25개×정책 8개"),
            ):
                area_column = "dong_code" if "DONG" in view_name else "district_code"
                cursor.execute(
                    f"""
                    SELECT {area_column}, category_name,
                           target_population_est, absolute_probability,
                           potential_demand, other_probability,
                           other_potential_demand, conditional_share
                    FROM {view_name}
                    """
                )
                oracle_region = _frame(
                    cursor.fetchall(),
                    ["area_code", "category_name", *NUMERIC_COLUMNS],
                )
                region_checks.append(
                    compare_keyed_numeric_frames(
                        local,
                        oracle_region,
                        key_columns=["area_code", "category_name"],
                        numeric_columns=NUMERIC_COLUMNS,
                        context=context,
                        absolute_tolerances=TOLERANCES,
                    )
                )

            print("[검증 진행] 6/6 행·키·총량 보존", flush=True)
            summary_check = _summary_check(cursor, run_id)
    except Exception as exc:
        result.update(
            {"status": "oracle_read_failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if connection is not None:
            connection.close()

    checks = [probability_check, grid_sample_check, *region_checks, summary_check]
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
