"""검증된 선호모델·확률·공간 잠재수요 산출물을 OCI에 업로드한다."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOADER = PROJECT_ROOT / "scripts/upload_oci_raw_data.py"

OUTPUTS: tuple[dict[str, Any], ...] = (
    {
        "key": "model",
        "source": PROJECT_ROOT
        / "models/preference_analysis/v1/preference_model_pipeline.joblib",
        "object_name": (
            "model-artifacts/preference/v1/preference_model_pipeline.joblib"
        ),
        "receipt": PROJECT_ROOT / ".oci_preference_model_upload_receipt.local.json",
    },
    {
        "key": "contract",
        "source": PROJECT_ROOT
        / "models/preference_analysis/v1/model_contract.json",
        "object_name": "model-artifacts/preference/v1/model_contract.json",
        "receipt": PROJECT_ROOT
        / ".oci_preference_contract_upload_receipt.local.json",
    },
    {
        "key": "probability",
        "source": PROJECT_ROOT
        / "data/processed/preference_analysis/model/"
        "sex_age_middle_category_preference_2024.csv",
        "object_name": (
            "standardized/preference/v1/reference_year=2024/"
            "sex_age_middle_category_preference_2024.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_preference_probability_upload_receipt.local.json",
        "expected_rows": 126,
    },
    {
        "key": "grid_demand",
        "source": PROJECT_ROOT
        / "data/processed/preference_analysis/spatial/"
        "grid_middle_category_preference_demand_2024.csv",
        "object_name": (
            "analytics/preference/v1/reference_year=2024/"
            "grid_middle_category_preference_demand_2024.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_preference_grid_demand_upload_receipt.local.json",
        "expected_rows": 484_224,
    },
    {
        "key": "dong_demand",
        "source": PROJECT_ROOT
        / "data/processed/preference_analysis/spatial/"
        "dong_middle_category_preference_demand_2024.csv",
        "object_name": (
            "analytics/preference/v1/reference_year=2024/"
            "dong_middle_category_preference_demand_2024.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_preference_dong_demand_upload_receipt.local.json",
        "expected_rows": 3_408,
    },
    {
        "key": "gu_demand",
        "source": PROJECT_ROOT
        / "data/processed/preference_analysis/spatial/"
        "gu_middle_category_preference_demand_2024.csv",
        "object_name": (
            "analytics/preference/v1/reference_year=2024/"
            "gu_middle_category_preference_demand_2024.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_preference_gu_demand_upload_receipt.local.json",
        "expected_rows": 200,
    },
    {
        "key": "validation",
        "source": PROJECT_ROOT
        / "data/processed/preference_analysis/spatial/"
        "spatial_validation_summary_2024.csv",
        "object_name": (
            "analytics/preference/v1/reference_year=2024/"
            "spatial_validation_summary_2024.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_preference_validation_upload_receipt.local.json",
        "expected_rows": 8,
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def validate_preference_outputs() -> dict[str, Any]:
    """업로드 전에 필수 파일·행 수·모델 해시·공간검증을 확인한다."""

    checked: dict[str, Any] = {}
    for item in OUTPUTS:
        path = Path(item["source"])
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"선호모델 산출물이 없거나 비어 있습니다: {path}")
        result: dict[str, Any] = {"size_bytes": path.stat().st_size}
        expected_rows = item.get("expected_rows")
        if expected_rows is not None:
            actual_rows = _csv_row_count(path)
            if actual_rows != expected_rows:
                raise ValueError(
                    f"{item['key']} 행 수가 다릅니다: "
                    f"actual={actual_rows:,}, expected={expected_rows:,}"
                )
            result["rows"] = actual_rows
        checked[str(item["key"])] = result

    contract_path = Path(OUTPUTS[1]["source"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected_model_hash = str(contract["model_artifact"]["sha256"])
    actual_model_hash = _sha256(Path(OUTPUTS[0]["source"]))
    if actual_model_hash != expected_model_hash:
        raise ValueError("모델 파일 SHA-256이 model_contract.json과 다릅니다.")

    validation_path = Path(OUTPUTS[-1]["source"])
    with validation_path.open("r", encoding="utf-8-sig", newline="") as source:
        validation_rows = list(csv.DictReader(source))
    failed = [row["check"] for row in validation_rows if row["status"] != "pass"]
    if failed:
        raise ValueError(f"통과하지 못한 공간검증이 있습니다: {failed}")

    return {
        "status": "preflight_ok",
        "files": checked,
        "model_sha256_matches_contract": True,
        "spatial_validation_passed": len(validation_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        preflight = validate_preference_outputs()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "preflight_failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(preflight, ensure_ascii=False, indent=2), flush=True)

    for index, item in enumerate(OUTPUTS, start=1):
        print(
            f"[업로드 진행] {index}/{len(OUTPUTS)} {item['key']}",
            flush=True,
        )
        command = [
            sys.executable,
            str(UPLOADER),
            "--source",
            str(item["source"]),
            "--object-name",
            str(item["object_name"]),
            "--receipt",
            str(item["receipt"]),
            "--bucket-kind",
            "artifact",
            "--reference-period",
            "2024",
        ]
        if args.replace:
            command.append("--replace")
        if args.dry_run:
            command.append("--dry-run")
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode

    print("선호모델·선호확률·공간 잠재수요 OCI 업로드 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
