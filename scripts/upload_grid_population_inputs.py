"""격자 lookup과 성·연령 대상자 추정 원본을 각 OCI bucket에 업로드한다."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOADER = PROJECT_ROOT / "scripts/upload_oci_raw_data.py"

UPLOADS = (
    {
        "source": PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv",
        "object_name": "landing/spatial/grid/2024/grid_pop_access.csv",
        "receipt": PROJECT_ROOT / ".oci_grid_lookup_upload_receipt.local.json",
        "bucket_kind": "raw",
    },
    {
        "source": PROJECT_ROOT
        / "analysis_table/data/output/서울시_격자_100m_문화누리대상자_성연령별_인구수.csv",
        "object_name": (
            "standardized/target_population/2024/"
            "grid_sex_age_target_population_proxy_2024.csv"
        ),
        "receipt": PROJECT_ROOT
        / ".oci_target_population_upload_receipt.local.json",
        "bucket_kind": "artifact",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for upload in UPLOADS:
        command = [
            sys.executable,
            str(UPLOADER),
            "--source",
            str(upload["source"]),
            "--object-name",
            str(upload["object_name"]),
            "--receipt",
            str(upload["receipt"]),
            "--bucket-kind",
            str(upload["bucket_kind"]),
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
    print("격자 lookup과 성별·연령별 대상자 추정 입력 업로드 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
