"""OCI data-access tests grouped by domain."""

from __future__ import annotations

# ---- consolidated from test_accessibility_etl.py ----
from pathlib import Path

from src.data_access.accessibility import (
    ACCESS_MODE_CODES,
    DEMAND_BASIS,
    METHOD_CODE,
    iter_frame_records,
    prepare_h3sfca_baseline_for_oracle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "notebooks/access/OUTPUT/h3sfca"


def _prepare():
    return prepare_h3sfca_baseline_for_oracle(
        grid_accessibility_path=OUTPUT_DIR / "h3sfca_격자_중분류_접근성.csv",
        facility_ratio_path=OUTPUT_DIR / "h3sfca_가맹점_공급수요비.csv",
        grid_summary_path=OUTPUT_DIR / "h3sfca_격자_요약.csv",
        dong_summary_path=OUTPUT_DIR / "h3sfca_행정동_중분류_요약.csv",
        category_summary_path=OUTPUT_DIR / "h3sfca_중분류_요약.csv",
    )


def test_real_h3sfca_baseline_prepares_without_changing_calculation() -> None:
    prepared = _prepare()

    assert len(prepared["grid"]) == 304_509
    assert prepared["grid"]["grid_cd"].nunique() == 56_496
    assert prepared["grid"]["category_code"].nunique() == 10
    assert set(prepared["grid"]["access_mode_code"]) == set(ACCESS_MODE_CODES.values())
    assert set(prepared["grid"]["method_code"]) == {METHOD_CODE}
    assert set(prepared["grid"]["demand_basis"]) == {DEMAND_BASIS}
    assert len(prepared["facility"]) == 4_282
    assert all(check["passed"] for check in prepared["summary_checks"])


def test_h3sfca_record_chunks_preserve_version_fields() -> None:
    prepared = _prepare()
    sample = prepared["grid"].head(2)

    chunks = list(iter_frame_records(sample, etl_run_id=19, chunk_size=1))

    assert len(chunks) == 2
    assert chunks[0][0]["etl_run_id"] == 19
    assert chunks[0][0]["method_code"] == METHOD_CODE
    assert chunks[0][0]["demand_basis"] == DEMAND_BASIS

# ---- consolidated from test_accessibility_repository.py ----
from pathlib import Path

import pytest

from src.data_access.accessibility import (
    FACILITY_RATIO_COLUMNS,
    GRID_ACCESSIBILITY_COLUMNS,
    load_accessibility_data,
    load_accessibility_from_local,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_accessibility_repository_returns_existing_csv_shape() -> None:
    grid, facility = load_accessibility_from_local(PROJECT_ROOT)

    assert list(grid.columns) == GRID_ACCESSIBILITY_COLUMNS
    assert list(facility.columns) == FACILITY_RATIO_COLUMNS
    assert len(grid) == 304_509
    assert grid["GRID_CD"].nunique() == 56_496
    assert len(facility) == 4_282
    assert not grid.duplicated(["접근수단", "GRID_CD", "중분류"]).any()


def test_accessibility_dispatch_requires_connection_for_oracle() -> None:
    with pytest.raises(ValueError, match="oracle_connection"):
        load_accessibility_data(backend="oracle", project_root=PROJECT_ROOT)


def test_accessibility_dispatch_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="local 또는 oracle"):
        load_accessibility_data(backend="cloud", project_root=PROJECT_ROOT)

# ---- consolidated from test_upload_accessibility_outputs.py ----
from scripts.upload_accessibility_outputs import (
    OUTPUTS,
    validate_accessibility_outputs,
)


def test_accessibility_upload_manifest_has_unique_baseline_destinations() -> None:
    object_names = [str(item["object_name"]) for item in OUTPUTS]
    receipts = [str(item["receipt"]) for item in OUTPUTS]

    assert len(OUTPUTS) == 5
    assert len(object_names) == len(set(object_names))
    assert len(receipts) == len(set(receipts))
    assert all("accessibility/h3sfca/baseline_v1/" in name for name in object_names)


def test_real_accessibility_outputs_pass_preflight() -> None:
    result = validate_accessibility_outputs()

    assert result["status"] == "preflight_ok"
    assert result["version"] == "baseline_v1"
    assert result["calculation_changed"] is False
    assert result["files"]["grid_accessibility"]["rows"] == 304_509
    assert result["files"]["facility_ratio"]["rows"] == 4_282
    assert all(check["passed"] for check in result["summary_checks"])
