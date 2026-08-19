from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OciSettings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCI SDK 설치, API 키 설정 및 Tokyo 리전 연결을 확인합니다."
    )
    parser.add_argument(
        "--settings-only",
        action="store_true",
        help="OCI API를 호출하지 않고 로컬 설정만 확인합니다.",
    )
    args = parser.parse_args()

    settings = OciSettings.from_env()
    result: dict[str, object] = {
        "status": "checking",
        "data_backend": settings.data_backend,
        "config_file": str(settings.config_file),
        "profile": settings.profile,
        "auth": settings.auth,
        "expected_region": settings.region,
        "compartment_name": settings.compartment_name,
        "raw_bucket": settings.raw_bucket,
        "artifact_bucket": settings.artifact_bucket,
    }

    errors = settings.validation_errors()
    if errors:
        result["status"] = "invalid_settings"
        result["errors"] = errors
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        import oci
        import oracledb
    except ImportError as exc:
        result["status"] = "missing_dependency"
        result["error"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result["oci_sdk_version"] = oci.__version__
    result["oracledb_version"] = oracledb.__version__

    if args.settings_only:
        result["status"] = "local_settings_ok"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not settings.config_file.is_file():
        result["status"] = "oci_config_missing"
        result["next_action"] = (
            "OCI Console에서 API 키를 등록한 뒤 ~/.oci/config를 생성하세요."
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        config = oci.config.from_file(
            file_location=str(settings.config_file),
            profile_name=settings.profile,
        )
        if settings.auth == "security_token":
            required = {"tenancy", "region", "key_file", "security_token_file"}
            missing = sorted(required.difference(config))
            if missing:
                raise ValueError(
                    "security token profile에 필수 항목이 없습니다: "
                    + ", ".join(missing)
                )
        else:
            oci.config.validate_config(config)
    except Exception as exc:
        result["status"] = "oci_config_invalid"
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    configured_region = config.get("region")
    result["configured_region"] = configured_region
    if configured_region != settings.region:
        result["status"] = "region_mismatch"
        result["error"] = (
            f"OCI config 리전 {configured_region!r}이 프로젝트 리전 "
            f"{settings.region!r}과 다릅니다."
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        if settings.auth == "security_token":
            token_path = Path(config["security_token_file"]).expanduser()
            token = token_path.read_text(encoding="utf-8")
            private_key = oci.signer.load_private_key_from_file(config["key_file"])
            signer = oci.auth.signers.SecurityTokenSigner(token, private_key)
            client_config = {"region": settings.region}
            identity = oci.identity.IdentityClient(client_config, signer=signer)
            object_storage = oci.object_storage.ObjectStorageClient(
                client_config, signer=signer
            )
        else:
            identity = oci.identity.IdentityClient(config)
            object_storage = oci.object_storage.ObjectStorageClient(config)
        tenancy = identity.get_tenancy(config["tenancy"]).data
        namespace = object_storage.get_namespace().data
    except Exception as exc:
        result["status"] = "oci_api_failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result.update(
        {
            "status": "oci_api_ok",
            "tenancy_name": tenancy.name,
            "object_storage_namespace": namespace,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
