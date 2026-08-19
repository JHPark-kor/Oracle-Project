from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OracleDbSettings
from src.data_access.merchant import load_merchant_for_oracle
from src.data_access.merchant import (
    compare_merchant_frames,
    load_merchant_data_from_oracle,
)
from src.data_access.oracle_validation import compare_keyed_numeric_frames


SOURCE_PATH = (
    PROJECT_ROOT
    / "data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx"
)
GRID_LOOKUP_PATH = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"


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
        result["status"] = "app_user_required"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        prepared = load_merchant_for_oracle(SOURCE_PATH, GRID_LOOKUP_PATH)
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
        oracle_analysis, oracle_quality = load_merchant_data_from_oracle(connection)
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
        compare_merchant_frames(prepared["analysis"], oracle_analysis),
        compare_keyed_numeric_frames(
            prepared["quality"],
            oracle_quality,
            key_columns=["check"],
            numeric_columns=["value"],
            context="가맹점 품질검사 5개",
        ),
    ]
    passed = all(bool(check["passed"]) for check in checks)
    result.update(
        {
            "status": "parity_ok" if passed else "parity_failed",
            "checks": checks,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
