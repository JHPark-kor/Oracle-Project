from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDA_DIR = PROJECT_ROOT / "notebooks/eda"
for path in (PROJECT_ROOT, EDA_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.data_access import OracleDbSettings
from run_kim_sunghyun_eda import _print_completion_summary, run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Oracle 카드 이용자료로 기존 EDA 01~04를 실행합니다."
    )
    parser.add_argument(
        "--merchant-backend",
        choices=["local", "oracle"],
        default="local",
    )
    args = parser.parse_args()
    settings = OracleDbSettings.from_env()
    errors = settings.validation_errors()
    if errors:
        raise ValueError("; ".join(errors))
    if settings.user != "MNC_APP":
        raise ValueError(".env.oci.local의 ORACLE_DB_USER=MNC_APP이 필요합니다.")

    import oracledb

    database_password = getpass.getpass("MNC_APP 데이터베이스 비밀번호: ")
    wallet_password = getpass.getpass("Wallet 비밀번호: ")
    connection = oracledb.connect(
        user=settings.user,
        password=database_password,
        dsn=settings.dsn,
        config_dir=str(settings.wallet_dir),
        wallet_location=str(settings.wallet_dir),
        wallet_password=wallet_password,
    )
    try:
        result = run_pipeline(
            project_root=PROJECT_ROOT,
            usage_backend="oracle",
            merchant_backend=args.merchant_backend,
            oracle_connection=connection,
        )
    finally:
        connection.close()
    _print_completion_summary(result)
    print("- 카드 이용 데이터 원본: Oracle MNCDEV")
    if args.merchant_backend == "oracle":
        print("- 가맹점 데이터 원본: Oracle MNCDEV")
    else:
        print("- 가맹점 데이터 원본: 기존 로컬 Excel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
