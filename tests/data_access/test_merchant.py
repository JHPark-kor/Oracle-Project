"""OCI data-access tests grouped by domain."""

# ---- consolidated from test_merchant_etl.py ----
from pathlib import Path

from src.data_access.merchant import load_merchant_for_oracle
from src.data_access.merchant import compare_merchant_frames


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    PROJECT_ROOT
    / "data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx"
)
GRID = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"


def test_real_merchant_snapshot_builds_unique_oracle_rows() -> None:
    prepared = load_merchant_for_oracle(SOURCE, GRID)
    quality = prepared["quality"].set_index("check")["value"].to_dict()
    rows = prepared["merchant_rows"]

    assert len(prepared["raw"]) == quality["raw_merchant_rows"] == 4_727
    assert len(prepared["analysis"]) == quality["analysis_merchant_rows"] == 4_722
    assert quality["exact_duplicate_rows"] == 5
    assert quality["invalid_coordinate_rows"] == 16
    assert quality["district_address_mismatch_rows"] == 37
    assert len(rows) == len({row["merchant_key"] for row in rows}) == 4_722
    assert len({row["district_code"] for row in rows}) == 25
    assert len({row["category_code"] for row in rows}) == 13
    assert sum(row["coordinate_valid"] == "N" for row in rows) == 16
    assert sum(row["district_mismatch"] == "Y" for row in rows) == 37


def test_merchant_comparison_ignores_order_but_detects_changed_value() -> None:
    prepared = load_merchant_for_oracle(SOURCE, GRID)
    local = prepared["analysis"]
    reordered = local.iloc[::-1].reset_index(drop=True)

    assert compare_merchant_frames(local, reordered)["passed"] is True

    changed = reordered.copy()
    changed.loc[0, "category_small"] = "변경된 값"
    result = compare_merchant_frames(local, changed)

    assert result["passed"] is False
    assert result["mismatch_by_column"]["category_small"] == 1
