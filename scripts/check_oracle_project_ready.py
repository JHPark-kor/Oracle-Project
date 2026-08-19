"""카드·가맹점·격자·선호·H3SFCA의 Oracle 준비상태를 한 번에 확인한다."""

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
from src.data_access.project_readiness import check_oracle_project_readiness


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
    started_at = time.monotonic()
    try:
        import oracledb

        print("[통합 점검] Oracle 최신 성공 실행과 행 수 집계 중...", flush=True)
        connection = oracledb.connect(
            user=settings.user,
            password=database_password,
            dsn=settings.dsn,
            config_dir=str(settings.wallet_dir),
            wallet_location=str(settings.wallet_dir),
            wallet_password=wallet_password,
        )
        readiness = check_oracle_project_readiness(connection)
    except Exception as exc:
        result.update(
            {"status": "oracle_read_failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if connection is not None:
            connection.close()

    result.update(readiness)
    result.update(
        {
            "status": (
                "project_oracle_ready"
                if readiness["all_checks_passed"]
                else "project_oracle_not_ready"
            ),
            "elapsed_seconds": round(time.monotonic() - started_at, 2),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if readiness["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
