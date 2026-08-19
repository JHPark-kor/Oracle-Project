from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access import OciSettings


DEFAULT_SOURCE = (
    PROJECT_ROOT / "data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx"
)
DEFAULT_OBJECT_NAME = (
    "landing/mnc_card/2021_2025/"
    "mnc_seoul_usage_issuance_2021_2025.xlsx"
)
UPLOAD_RECEIPT = PROJECT_ROOT / ".oci_card_upload_receipt.local.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_receipt(result: dict[str, object], receipt_path: Path) -> None:
    receipt = {
        "object_uri": result["object_uri"],
        "sha256": result["sha256"],
        "size_bytes": result["size_bytes"],
        "bucket": result["bucket"],
        "object_name": result["object_name"],
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _object_metadata(
    source_name: str,
    file_hash: str,
    reference_period: str,
) -> dict[str, str]:
    """OCI HTTP metadata에 안전하도록 원본 파일명을 ASCII로 보존한다."""

    return {
        "sha256": file_hash,
        "source-name": quote(source_name, safe=""),
        "source-name-encoding": "percent",
        "reference-period": reference_period,
    }


def _build_object_client(settings: OciSettings):
    import oci

    config = oci.config.from_file(
        file_location=str(settings.config_file),
        profile_name=settings.profile,
    )
    if settings.auth == "security_token":
        token_path = Path(config["security_token_file"]).expanduser()
        token = token_path.read_text(encoding="utf-8")
        private_key = oci.signer.load_private_key_from_file(config["key_file"])
        signer = oci.auth.signers.SecurityTokenSigner(token, private_key)
        client = oci.object_storage.ObjectStorageClient(
            {"region": settings.region}, signer=signer
        )
    else:
        oci.config.validate_config(config)
        client = oci.object_storage.ObjectStorageClient(config)
    return client


def main() -> int:
    parser = argparse.ArgumentParser(
        description="검증된 문화누리카드 원본을 OCI Object Storage에 올립니다."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--object-name", default=DEFAULT_OBJECT_NAME)
    parser.add_argument("--receipt", type=Path, default=UPLOAD_RECEIPT)
    parser.add_argument("--reference-period", default="2021-2025")
    parser.add_argument(
        "--bucket-kind",
        choices=("raw", "artifact"),
        default="raw",
        help="원본은 raw, 정규화·분석 준비 산출물은 artifact bucket을 사용합니다.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="같은 경로에 다른 해시의 객체가 있을 때만 명시적으로 교체합니다.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = OciSettings.from_env()
    errors = settings.validation_errors()
    source = args.source.expanduser().resolve()
    bucket = (
        settings.raw_bucket if args.bucket_kind == "raw" else settings.artifact_bucket
    )
    receipt_path = args.receipt.expanduser()
    if not receipt_path.is_absolute():
        receipt_path = (PROJECT_ROOT / receipt_path).resolve()
    result: dict[str, object] = {
        "status": "checking",
        "source": str(source),
        "bucket": bucket,
        "object_name": args.object_name,
    }
    if errors:
        result.update({"status": "invalid_settings", "errors": errors})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    if not source.is_file() or source.stat().st_size == 0:
        result.update({"status": "source_missing_or_empty"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    file_hash = _sha256(source)
    file_size = source.stat().st_size
    result.update({"sha256": file_hash, "size_bytes": file_size})
    if args.dry_run:
        result["status"] = "dry_run_ok"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    try:
        client = _build_object_client(settings)
        namespace = client.get_namespace().data
        existing = None
        try:
            existing = client.head_object(
                namespace,
                bucket,
                args.object_name,
            )
        except Exception as exc:
            if getattr(exc, "status", None) != 404:
                raise

        if existing is not None:
            existing_hash = (existing.headers.get("opc-meta-sha256") or "").lower()
            existing_size = int(existing.headers.get("content-length", -1))
            if existing_hash == file_hash and existing_size == file_size:
                result.update(
                    {
                        "status": "already_uploaded",
                        "object_uri": (
                            f"oci://{bucket}@{namespace}/"
                            f"{args.object_name}"
                        ),
                    }
                )
                _write_receipt(result, receipt_path)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            if not args.replace:
                result.update(
                    {
                        "status": "different_object_exists",
                        "error": "교체하려면 파일을 확인한 뒤 --replace를 사용하세요.",
                        "existing_sha256": existing_hash or None,
                        "existing_size_bytes": existing_size,
                    }
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1

        with source.open("rb") as body:
            response = client.put_object(
                namespace,
                bucket,
                args.object_name,
                body,
                content_length=file_size,
                content_type=(
                    mimetypes.guess_type(source.name)[0]
                    or "application/octet-stream"
                ),
                opc_meta=_object_metadata(
                    source.name,
                    file_hash,
                    args.reference_period,
                ),
            )
    except Exception as exc:
        is_auth_error = (
            getattr(exc, "status", None) == 401
            or getattr(exc, "code", None) == "NotAuthenticated"
        )
        result.update(
            {
                "status": "upload_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "next_action": (
                    "인증 만료 오류이면 터미널에서 `.venv/bin/oci session authenticate "
                    "--region ap-tokyo-1 --profile-name MNC_SETUP`을 실행한 뒤 "
                    "다시 시도하세요."
                    if is_auth_error
                    else "위 오류 내용을 확인한 뒤 같은 실행 항목을 다시 실행하세요."
                ),
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result.update(
        {
            "status": "uploaded",
            "etag": response.headers.get("etag"),
            "object_uri": (
                f"oci://{bucket}@{namespace}/{args.object_name}"
            ),
        }
    )
    _write_receipt(result, receipt_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
