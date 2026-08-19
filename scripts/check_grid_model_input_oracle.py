"""Oracle의 15세 이상 격자 대상자 입력이 선호모델에 바로 쓰이는지 확인한다."""

from __future__ import annotations

import getpass
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OracleDbSettings
from src.data_access.grid_population import (
    summarize_grid_model_input_from_oracle,
)


EXPECTED_SUMMARY = {
    "rows": 847_392,
    "grid_count": 60_528,
    "sex_count": 2,
    "age_count": 7,
    "target_population_15plus": 545_692,
    "duplicate_keys": 0,
    "negative_population_rows": 0,
    "missing_required_rows": 0,
    "reference_year_count": 1,
    "reference_year_min": 2024,
    "reference_year_max": 2024,
    "non_proxy_rows": 0,
    "overlap_adjusted_rows": 0,
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

    database_password = getpass.getpass("MNC_APP 데이터베이스 비밀번호: ")
    wallet_password = getpass.getpass("Wallet 비밀번호: ")
    if not database_password or not wallet_password:
        result["status"] = "password_missing"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    connection = None
    try:
        import oracledb

        started_at = time.monotonic()
        print("[검사 진행] Oracle 연결 및 모델 입력 집계 중...", flush=True)
        connection = oracledb.connect(
            user=settings.user,
            password=database_password,
            dsn=settings.dsn,
            config_dir=str(settings.wallet_dir),
            wallet_location=str(settings.wallet_dir),
            wallet_password=wallet_password,
        )
        summary = summarize_grid_model_input_from_oracle(connection)
    except Exception as exc:
        result.update(
            {"status": "oracle_read_failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if connection is not None:
            connection.close()

    checks = {
        key: summary[key] == expected
        for key, expected in EXPECTED_SUMMARY.items()
    }
    all_checks_passed = all(checks.values())
    result.update(summary)
    result.update(
        {
            "status": (
                "model_input_ready" if all_checks_passed else "model_input_invalid"
            ),
            "checks": checks,
            "all_checks_passed": all_checks_passed,
            "elapsed_seconds": round(time.monotonic() - started_at, 2),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
