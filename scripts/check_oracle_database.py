from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OracleDbSettings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MNCDEV Wallet 설정과 Oracle Database 연결을 확인합니다."
    )
    parser.add_argument(
        "--settings-only",
        action="store_true",
        help="비밀번호 입력과 DB 접속 없이 Wallet 설정만 확인합니다.",
    )
    args = parser.parse_args()

    settings = OracleDbSettings.from_env()
    result: dict[str, object] = {
        "status": "checking",
        "user": settings.user,
        "dsn": settings.dsn,
        "wallet_dir": (
            str(settings.wallet_dir) if settings.wallet_dir is not None else None
        ),
    }

    errors = settings.validation_errors()
    if errors:
        result["status"] = "invalid_settings"
        result["errors"] = errors
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    if args.settings_only:
        result["status"] = "wallet_settings_ok"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    try:
        import oracledb
    except ImportError as exc:
        result["status"] = "missing_dependency"
        result["error"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    database_password = getpass.getpass(
        f"{settings.user} 데이터베이스 비밀번호: "
    )
    wallet_password = getpass.getpass("Wallet 비밀번호: ")
    if not database_password or not wallet_password:
        result["status"] = "password_missing"
        result["error"] = "DB 비밀번호와 Wallet 비밀번호가 모두 필요합니다."
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
                SELECT
                    SYS_CONTEXT('USERENV', 'DB_NAME'),
                    SYS_CONTEXT('USERENV', 'CURRENT_USER'),
                    SYS_CONTEXT('USERENV', 'SERVICE_NAME')
                FROM dual
                """
            )
            db_name, current_user, service_name = cursor.fetchone()
    except Exception as exc:
        result["status"] = "database_connection_failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if connection is not None:
            connection.close()

    result.update(
        {
            "status": "database_connection_ok",
            "database_name": db_name,
            "current_user": current_user,
            "service_name": service_name,
            "oracledb_version": oracledb.__version__,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
