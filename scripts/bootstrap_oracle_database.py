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
from src.data_access.oracle_schema import (
    APP_SCHEMA,
    bootstrap_admin_objects,
    bootstrap_app_schema,
    bootstrap_plan,
    validate_app_password,
)


def _connect(
    oracledb_module: object,
    settings: OracleDbSettings,
    user: str,
    password: str,
    wallet_password: str,
):
    return oracledb_module.connect(
        user=user,
        password=password,
        dsn=settings.dsn,
        config_dir=str(settings.wallet_dir),
        wallet_location=str(settings.wallet_dir),
        wallet_password=wallet_password,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MNCDEV에 프로젝트 전용 MNC_APP 계정과 기본 스키마를 만듭니다."
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="DB에 접속하거나 변경하지 않고 생성 계획만 출력합니다.",
    )
    args = parser.parse_args()

    if args.plan:
        print(json.dumps(bootstrap_plan(), ensure_ascii=False, indent=2))
        return 0

    settings = OracleDbSettings.from_env()
    result: dict[str, object] = {
        "status": "checking",
        "dsn": settings.dsn,
        "wallet_dir": (
            str(settings.wallet_dir) if settings.wallet_dir is not None else None
        ),
        "app_user": APP_SCHEMA,
    }
    errors = settings.validation_errors()
    if errors:
        result.update({"status": "invalid_settings", "errors": errors})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    if settings.user != "ADMIN":
        result.update(
            {
                "status": "admin_user_required",
                "error": (
                    "최초 생성 시 .env.oci.local의 ORACLE_DB_USER는 "
                    "ADMIN이어야 합니다."
                ),
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        import oracledb
    except ImportError as exc:
        result.update({"status": "missing_dependency", "error": str(exc)})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    admin_password = getpass.getpass("ADMIN 데이터베이스 비밀번호: ")
    wallet_password = getpass.getpass("Wallet 비밀번호: ")
    app_password = getpass.getpass("새 MNC_APP 데이터베이스 비밀번호: ")
    app_password_confirm = getpass.getpass("MNC_APP 비밀번호 확인: ")
    if not admin_password or not wallet_password or not app_password:
        result.update(
            {
                "status": "password_missing",
                "error": "ADMIN, Wallet, MNC_APP 비밀번호가 모두 필요합니다.",
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    if app_password != app_password_confirm:
        result.update(
            {"status": "password_mismatch", "error": "MNC_APP 비밀번호가 다릅니다."}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    try:
        validate_app_password(app_password)
    except ValueError as exc:
        result.update({"status": "invalid_app_password", "error": str(exc)})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    admin_connection = None
    app_connection = None
    try:
        admin_connection = _connect(
            oracledb,
            settings,
            "ADMIN",
            admin_password,
            wallet_password,
        )
        admin_result = bootstrap_admin_objects(admin_connection, app_password)
        admin_connection.close()
        admin_connection = None

        app_connection = _connect(
            oracledb,
            settings,
            APP_SCHEMA,
            app_password,
            wallet_password,
        )
        schema_result = bootstrap_app_schema(app_connection)
    except Exception as exc:
        result.update(
            {
                "status": "bootstrap_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        if admin_connection is not None:
            admin_connection.close()
        if app_connection is not None:
            app_connection.close()

    result.update(
        {
            "status": "bootstrap_ok",
            "admin_objects": admin_result,
            "app_schema": schema_result,
            "next_step": (
                ".env.oci.local의 ORACLE_DB_USER를 MNC_APP으로 바꾼 뒤 "
                "OCI 02 연결 확인을 다시 실행하세요."
            ),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
