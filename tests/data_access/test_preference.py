"""OCI data-access tests grouped by domain."""

from __future__ import annotations

# ---- consolidated from test_preference_etl.py ----
from pathlib import Path

import numpy as np

from src.data_access.preference import (
    build_preference_category_rows,
    build_preference_supply_bridge_rows,
    iter_frame_records,
    prepare_preference_for_oracle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBABILITY = (
    PROJECT_ROOT
    / "data/processed/preference_analysis/model/"
    "sex_age_middle_category_preference_2024.csv"
)
GRID_DEMAND = (
    PROJECT_ROOT
    / "data/processed/preference_analysis/spatial/"
    "grid_middle_category_preference_demand_2024.csv"
)


def test_real_preference_outputs_prepare_for_oracle() -> None:
    prepared = prepare_preference_for_oracle(PROBABILITY, GRID_DEMAND)

    assert len(prepared["category_rows"]) == 9
    assert len(prepared["bridge_rows"]) == 8
    assert len(prepared["probability"]) == 126
    assert len(prepared["grid_demand"]) == 484_224
    assert prepared["grid_demand"]["grid_cd"].nunique() == 60_528
    assert np.isclose(
        prepared["probability"].groupby(["sex_code", "age_code"])[
            "absolute_probability"
        ].sum().to_numpy(),
        1.0,
    ).all()


def test_preference_category_contract_keeps_other_out_of_supply_bridge() -> None:
    categories = build_preference_category_rows()
    bridges = build_preference_supply_bridge_rows()

    assert sum(row["supported_flag"] == "Y" for row in categories) == 8
    assert sum(row["supported_flag"] == "N" for row in categories) == 1
    assert len({row["from_category_code"] for row in bridges}) == 8
    assert all(row["mapping_status"] == "DIRECT" for row in bridges)


def test_record_chunks_convert_nan_to_none() -> None:
    prepared = prepare_preference_for_oracle(PROBABILITY, GRID_DEMAND)
    zero_grid = prepared["grid_demand"].loc[
        prepared["grid_demand"]["target_population_est"].eq(0)
    ].head(1)

    records = list(iter_frame_records(zero_grid, etl_run_id=11, chunk_size=1))

    assert records[0][0]["etl_run_id"] == 11
    assert records[0][0]["absolute_probability"] is None
    assert records[0][0]["other_probability"] is None
    assert records[0][0]["conditional_share"] is None

# ---- consolidated from test_preference_repository.py ----
from pathlib import Path

import numpy as np
import pytest

from src.data_access.preference import (
    GRID_DEMAND_COLUMNS,
    PROBABILITY_COLUMNS,
    load_preference_data,
    load_preference_from_local,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_preference_repository_returns_existing_output_contract() -> None:
    probability, grid = load_preference_from_local(PROJECT_ROOT)

    assert list(probability.columns) == PROBABILITY_COLUMNS
    assert len(probability) == 126
    assert np.allclose(
        probability.groupby(["sex_code", "age_code"])[
            "preference_probability_absolute"
        ].sum(),
        1.0,
    )
    assert list(grid.columns) == GRID_DEMAND_COLUMNS
    assert len(grid) == 484_224
    assert grid["GRID_CD"].nunique() == 60_528
    assert not grid.duplicated(["GRID_CD", "middle_category"]).any()


def test_preference_dispatch_requires_connection_for_oracle() -> None:
    with pytest.raises(ValueError, match="oracle_connection"):
        load_preference_data(backend="oracle", project_root=PROJECT_ROOT)


def test_preference_dispatch_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="local 또는 oracle"):
        load_preference_data(backend="cloud", project_root=PROJECT_ROOT)

# ---- consolidated from test_upload_preference_outputs.py ----
from scripts.upload_preference_outputs import OUTPUTS, validate_preference_outputs


def test_preference_upload_manifest_has_unique_destinations_and_receipts() -> None:
    object_names = [str(item["object_name"]) for item in OUTPUTS]
    receipts = [str(item["receipt"]) for item in OUTPUTS]

    assert len(OUTPUTS) == 7
    assert len(object_names) == len(set(object_names))
    assert len(receipts) == len(set(receipts))
    assert all("preference/v1/" in name for name in object_names)


def test_real_preference_outputs_pass_preflight() -> None:
    result = validate_preference_outputs()

    assert result["status"] == "preflight_ok"
    assert result["model_sha256_matches_contract"] is True
    assert result["spatial_validation_passed"] == 8
    assert result["files"]["probability"]["rows"] == 126
    assert result["files"]["grid_demand"]["rows"] == 484_224
