"""기존 H3SFCA 산출물 5개를 변경 없이 OCI Object Storage에 업로드한다."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_access.accessibility import (
    EXPECTED_ROWS,
    prepare_h3sfca_baseline_for_oracle,
)


UPLOADER = PROJECT_ROOT / "scripts/upload_oci_raw_data.py"
OUTPUT_DIR = PROJECT_ROOT / "notebooks/access/OUTPUT/h3sfca"

OUTPUTS: tuple[dict[str, Any], ...] = (
    {
        "key": "grid_accessibility",
        "source": OUTPUT_DIR / "h3sfca_격자_중분류_접근성.csv",
        "object_name": (
            "analytics/accessibility/h3sfca/baseline_v1/"
            "h3sfca_격자_중분류_접근성.csv"
        ),
        "receipt": PROJECT_ROOT / ".oci_h3sfca_grid_upload_receipt.local.json",
    },
    {
        "key": "facility_ratio",
        "source": OUTPUT_DIR / "h3sfca_가맹점_공급수요비.csv",
        "object_name": (
            "analytics/accessibility/h3sfca/baseline_v1/"
            "h3sfca_가맹점_공급수요비.csv"
        ),
        "receipt": PROJECT_ROOT / ".oci_h3sfca_facility_upload_receipt.local.json",
    },
    {
        "key": "grid_summary",
        "source": OUTPUT_DIR / "h3sfca_격자_요약.csv",
        "object_name": (
            "analytics/accessibility/h3sfca/baseline_v1/h3sfca_격자_요약.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_h3sfca_grid_summary_upload_receipt.local.json",
    },
    {
        "key": "dong_summary",
        "source": OUTPUT_DIR / "h3sfca_행정동_중분류_요약.csv",
        "object_name": (
            "analytics/accessibility/h3sfca/baseline_v1/"
            "h3sfca_행정동_중분류_요약.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_h3sfca_dong_summary_upload_receipt.local.json",
    },
    {
        "key": "category_summary",
        "source": OUTPUT_DIR / "h3sfca_중분류_요약.csv",
        "object_name": (
            "analytics/accessibility/h3sfca/baseline_v1/"
            "h3sfca_중분류_요약.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_h3sfca_category_summary_upload_receipt.local.json",
    },
)


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def validate_accessibility_outputs() -> dict[str, Any]:
    """기존 5개 파일의 행 수·키·수치와 요약 정합성을 업로드 전에 확인한다."""

    files: dict[str, dict[str, int]] = {}
    by_key = {str(item["key"]): item for item in OUTPUTS}
    for key, item in by_key.items():
        path = Path(item["source"])
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"H3SFCA 산출물이 없거나 비어 있습니다: {path}")
        rows = _csv_row_count(path)
        if rows != EXPECTED_ROWS[key]:
            raise ValueError(
                f"{key} 행 수가 다릅니다: "
                f"actual={rows:,}, expected={EXPECTED_ROWS[key]:,}"
            )
        files[key] = {"rows": rows, "size_bytes": path.stat().st_size}

    prepared = prepare_h3sfca_baseline_for_oracle(
        grid_accessibility_path=by_key["grid_accessibility"]["source"],
        facility_ratio_path=by_key["facility_ratio"]["source"],
        grid_summary_path=by_key["grid_summary"]["source"],
        dong_summary_path=by_key["dong_summary"]["source"],
        category_summary_path=by_key["category_summary"]["source"],
    )
    return {
        "status": "preflight_ok",
        "version": "baseline_v1",
        "calculation_changed": False,
        "files": files,
        "summary_checks": prepared["summary_checks"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        preflight = validate_accessibility_outputs()
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
        print(f"[업로드 진행] {index}/{len(OUTPUTS)} {item['key']}", flush=True)
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
            "target=2024;merchant=2026-07-06;baseline=v1",
        ]
        if args.replace:
            command.append("--replace")
        if args.dry_run:
            command.append("--dry-run")
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode

    print("기존 H3SFCA baseline_v1 산출물 OCI 업로드 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
