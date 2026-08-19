"""OCI data-access tests grouped by domain."""

# ---- consolidated from test_card_usage_etl.py ----
from pathlib import Path

from src.data_access.card_usage import (
    MIDDLE_CATEGORY_CODES,
    RAW_CATEGORY_CODES,
    build_admin_area_rows,
    build_category_rows,
    load_card_usage_for_oracle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_category_mapping_covers_27_raw_and_13_middle_categories() -> None:
    dimensions, bridges = build_category_rows()

    assert len(RAW_CATEGORY_CODES) == 27
    assert len(MIDDLE_CATEGORY_CODES) == 13
    assert len(dimensions) == 40
    assert len(bridges) == 27
    assert len({row["from_category_code"] for row in bridges}) == 27
    assert len({row["to_category_code"] for row in bridges}) == 13


def test_grid_lookup_builds_seoul_and_25_unique_districts() -> None:
    rows = build_admin_area_rows(
        PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"
    )

    assert len(rows) == 26
    assert rows[0]["area_code"] == "11"
    assert rows[0]["area_level"] == "SIDO"
    district_rows = [row for row in rows if row["area_level"] == "GU"]
    assert len({row["area_code"] for row in district_rows}) == 25
    assert len({row["area_name"] for row in district_rows}) == 25


def test_real_card_source_passes_all_checks_and_conserves_totals() -> None:
    prepared = load_card_usage_for_oracle(
        PROJECT_ROOT
        / "data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx",
        PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv",
    )

    assert prepared["quality"]["passed"].all()
    assert len(prepared["raw_rows"]) == 3_375
    assert len(prepared["year_rows"]) == 125
    assert len(prepared["middle_rows"]) == 1_625
    assert len(prepared["sex_rows"]) == 250
    assert len(prepared["age_rows"]) == 1_375

# ---- consolidated from test_card_usage_repository.py ----
from pathlib import Path

import pandas as pd

from src.data_access.card_usage import load_card_usage_for_oracle
from src.data_access.card_usage import (
    assemble_usage_frame,
    validate_oracle_usage_frame,
)
from src.data_access.oracle_validation import compare_keyed_numeric_frames


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _normalized_frames(prepared):
    area_name = {
        row["area_code"]: row["area_name"] for row in prepared["admin_rows"]
    }
    year = pd.DataFrame(prepared["year_rows"]).rename(
        columns={
            "reference_year": "year",
            "budget_amount_won": "budget_won",
            "issued_card_count": "issued_cards",
            "user_count": "users",
            "usage_count": "transactions",
            "culture_exp_count": "culture_experience_transactions",
            "culture_exp_pct": "culture_experience_transaction_pct",
        }
    )
    year["district"] = year.pop("district_code").map(area_name)
    year = year[
        [
            "year",
            "district",
            "budget_won",
            "issued_cards",
            "users",
            "issued_amount_won",
            "used_amount_won",
            "transactions",
            "culture_experience_transactions",
            "culture_experience_transaction_pct",
        ]
    ]
    sex = pd.DataFrame(prepared["sex_rows"]).rename(
        columns={"reference_year": "year"}
    )
    sex["district"] = sex.pop("district_code").map(area_name)
    age = pd.DataFrame(prepared["age_rows"]).rename(
        columns={"reference_year": "year"}
    )
    age["district"] = age.pop("district_code").map(area_name)
    raw = pd.DataFrame(prepared["raw_rows"]).rename(
        columns={"reference_year": "year", "district_name": "district"}
    )
    return year, sex, age, raw


def test_normalized_oracle_shape_reconstructs_existing_eda_input() -> None:
    prepared = load_card_usage_for_oracle(
        PROJECT_ROOT
        / "data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx",
        PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv",
    )
    year, sex, age, raw = _normalized_frames(prepared)

    reconstructed = assemble_usage_frame(year, sex, age, raw)
    local = prepared["usage"].sort_values(["year", "district"]).reset_index(drop=True)
    numeric_columns = [column for column in local if column not in {"year", "district"}]
    tolerance_columns = {
        column: 1e-8
        for column in numeric_columns
        if column.endswith("_pct")
        or column.startswith("used_per_")
        or column.startswith("transactions_per_")
        or column == "average_transaction_won"
    }
    comparison = compare_keyed_numeric_frames(
        local,
        reconstructed,
        key_columns=["year", "district"],
        numeric_columns=numeric_columns,
        context="EDA 카드 입력 전체 열",
        absolute_tolerances=tolerance_columns,
    )

    assert reconstructed.shape == local.shape == (125, 88)
    assert comparison["passed"] is True
    assert validate_oracle_usage_frame(reconstructed)["passed"].all()
