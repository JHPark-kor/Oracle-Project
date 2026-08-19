from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OracleDbSettings
from src.data_access.card_usage import load_card_usage_for_oracle
from src.data_access.card_usage import load_usage_data_from_oracle
from src.data_access.oracle_validation import compare_keyed_numeric_frames


SOURCE_PATH = (
    PROJECT_ROOT / "data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx"
)
GRID_LOOKUP_PATH = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"
PIPELINE_NAME = "card_usage_2021_2025_raw27_to_mid13_v2"


def _rows_to_frame(cursor, query: str, columns: list[str], **binds) -> pd.DataFrame:
    cursor.execute(query, **binds)
    return pd.DataFrame(cursor.fetchall(), columns=columns)


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
    if settings.user != "MNC_APP":
        result.update(
            {"status": "app_user_required", "error": "ORACLE_DB_USER=MNC_APP이 필요합니다."}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        prepared = load_card_usage_for_oracle(SOURCE_PATH, GRID_LOOKUP_PATH)
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
                SELECT MAX(etl_run_id) FROM META_ETL_RUN
                WHERE pipeline_name = :pipeline_name AND status = 'SUCCESS'
                """,
                pipeline_name=PIPELINE_NAME,
            )
            value = cursor.fetchone()[0]
            if value is None:
                raise ValueError("성공한 카드 이용 ETL 실행이 없습니다.")
            run_id = int(value)

            oracle_raw = _rows_to_frame(
                cursor,
                """
                SELECT reference_year, district_name, source_category_name,
                       usage_amount_won, usage_count
                FROM STG_CARD_USAGE_RAW27
                WHERE etl_run_id = :etl_run_id
                """,
                [
                    "reference_year",
                    "district_name",
                    "source_category_name",
                    "usage_amount_won",
                    "usage_count",
                ],
                etl_run_id=run_id,
            )
            oracle_year = _rows_to_frame(
                cursor,
                """
                SELECT reference_year, district_code, issued_card_count, user_count,
                       issued_amount_won, budget_amount_won,
                       used_amount_won, usage_count,
                       culture_exp_count, culture_exp_pct
                FROM FACT_CARD_GU_YEAR
                """,
                [
                    "reference_year",
                    "district_code",
                    "issued_card_count",
                    "user_count",
                    "issued_amount_won",
                    "budget_amount_won",
                    "used_amount_won",
                    "usage_count",
                    "culture_exp_count",
                    "culture_exp_pct",
                ],
            )
            oracle_middle = _rows_to_frame(
                cursor,
                """
                SELECT reference_year, district_code, scheme_code, category_code,
                       usage_amount_won, usage_count
                FROM FACT_CARD_GU_CAT
                WHERE scheme_code = 'SUPPLY_MID13'
                """,
                [
                    "reference_year",
                    "district_code",
                    "scheme_code",
                    "category_code",
                    "usage_amount_won",
                    "usage_count",
                ],
            )
            oracle_sex = _rows_to_frame(
                cursor,
                """
                SELECT reference_year, district_code, sex_code,
                       issued_card_count, used_amount_won
                FROM FACT_CARD_GU_SEX
                """,
                [
                    "reference_year",
                    "district_code",
                    "sex_code",
                    "issued_card_count",
                    "used_amount_won",
                ],
            )
            oracle_age = _rows_to_frame(
                cursor,
                """
                SELECT reference_year, district_code, age_code, issued_card_count
                FROM FACT_CARD_GU_AGE
                """,
                [
                    "reference_year",
                    "district_code",
                    "age_code",
                    "issued_card_count",
                ],
            )
        oracle_usage, oracle_quality = load_usage_data_from_oracle(connection)
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
        compare_keyed_numeric_frames(
            pd.DataFrame(prepared["raw_rows"]),
            oracle_raw,
            key_columns=["reference_year", "district_name", "source_category_name"],
            numeric_columns=["usage_amount_won", "usage_count"],
            context="원본 27분류 staging",
        ),
        compare_keyed_numeric_frames(
            pd.DataFrame(prepared["year_rows"]),
            oracle_year,
            key_columns=["reference_year", "district_code"],
            numeric_columns=[
                "issued_card_count",
                "user_count",
                "issued_amount_won",
                "budget_amount_won",
                "used_amount_won",
                "usage_count",
                "culture_exp_count",
                "culture_exp_pct",
            ],
            context="자치구 연도별 카드 이용",
            absolute_tolerances={"culture_exp_pct": 1e-8},
        ),
        compare_keyed_numeric_frames(
            pd.DataFrame(prepared["middle_rows"]),
            oracle_middle,
            key_columns=[
                "reference_year",
                "district_code",
                "scheme_code",
                "category_code",
            ],
            numeric_columns=["usage_amount_won", "usage_count"],
            context="자치구 연도별 13중분류",
        ),
        compare_keyed_numeric_frames(
            pd.DataFrame(prepared["sex_rows"]),
            oracle_sex,
            key_columns=["reference_year", "district_code", "sex_code"],
            numeric_columns=["issued_card_count", "used_amount_won"],
            context="자치구 연도별 성별",
        ),
        compare_keyed_numeric_frames(
            pd.DataFrame(prepared["age_rows"]),
            oracle_age,
            key_columns=["reference_year", "district_code", "age_code"],
            numeric_columns=["issued_card_count"],
            context="자치구 연도별 연령별",
        ),
    ]
    local_usage = prepared["usage"]
    numeric_columns = [
        column for column in local_usage if column not in {"year", "district"}
    ]
    tolerance_columns = {
        column: 1e-8
        for column in numeric_columns
        if column.endswith("_pct")
        or column.startswith("used_per_")
        or column.startswith("transactions_per_")
        or column == "average_transaction_won"
    }
    checks.append(
        compare_keyed_numeric_frames(
            local_usage,
            oracle_usage,
            key_columns=["year", "district"],
            numeric_columns=numeric_columns,
            context="EDA 공통 입력 전체 88열",
            absolute_tolerances=tolerance_columns,
        )
    )
    passed = all(bool(check["passed"]) for check in checks)
    result.update(
        {
            "status": "parity_ok" if passed else "parity_failed",
            "etl_run_id": run_id,
            "checks": checks,
            "oracle_internal_quality_checks": {
                "passed": int(oracle_quality["passed"].sum()),
                "total": int(len(oracle_quality)),
            },
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
