"""OCI data-access tests grouped by domain."""

from __future__ import annotations

# ---- consolidated from test_grid_population_etl.py ----
from pathlib import Path

import pandas as pd

from src.data_access.grid_population import (
    iter_fact_records,
    prepare_grid_population_for_oracle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_SOURCE = (
    PROJECT_ROOT
    / "analysis_table/data/output/서울시_격자_100m_문화누리대상자_성연령별_인구수.csv"
)
GRID_LOOKUP = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"


def test_real_grid_population_preserves_keys_and_totals() -> None:
    prepared = prepare_grid_population_for_oracle(TARGET_SOURCE, GRID_LOOKUP)
    fact = prepared["fact"]

    assert len(prepared["grid_rows"]) == 60_528
    assert len(prepared["admin_rows"]) == 1 + 25 + 426
    assert len(fact) == 1_089_504
    assert len(prepared["model_input"]) == 847_392
    assert prepared["source_total"] == prepared["aligned_total"] == 582_549
    assert prepared["model_total"] == 545_692
    assert not fact.duplicated(["grid_cd", "sex_code", "aligned_age_order"]).any()
    assert set(fact["proxy_flag"]) == {"Y"}
    assert set(fact["overlap_adjusted"]) == {"N"}
    assert set(fact["model_applicable"]) == {"Y", "N"}


def test_fact_record_chunks_convert_nullable_model_age() -> None:
    frame = pd.DataFrame(
        [
            {
                "reference_year": 2024,
                "grid_cd": "GRID1",
                "sex_code": 1,
                "sex_label": "남자",
                "aligned_age_order": 0,
                "aligned_age_group": "0-5세",
                "model_age_code": pd.NA,
                "model_age_label": pd.NA,
                "model_applicable": "N",
                "alignment_status": "대상연령_확인필요",
                "alignment_note": "확인 필요",
                "source_age_groups": "0-5세",
                "source_age_group_count": 1,
                "target_population_est": 3,
                "proxy_flag": "Y",
                "overlap_adjusted": "N",
                "estimate_method": "test",
            }
        ]
    )

    chunks = list(iter_fact_records(frame, etl_run_id=7, chunk_size=1))

    assert len(chunks) == 1
    assert chunks[0][0]["etl_run_id"] == 7
    assert chunks[0][0]["model_age_code"] is None
    assert chunks[0][0]["model_age_label"] is None

# ---- consolidated from test_grid_population_repository.py ----
from pathlib import Path

import pytest

from src.data_access.grid_population import (
    load_grid_model_input,
    load_grid_model_input_from_local,
    summarize_grid_model_input_from_oracle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _FakeCursor:
    def __init__(self, row):
        self.row = row
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query: str) -> None:
        self.query = query

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, row):
        self.cursor_instance = _FakeCursor(row)

    def cursor(self):
        return self.cursor_instance


def test_summary_uses_database_aggregation_without_fetching_all_rows() -> None:
    row = (
        847_392,
        60_528,
        2,
        7,
        545_692,
        0,
        0,
        0,
        1,
        2024,
        2024,
        0,
        0,
    )
    connection = _FakeConnection(row)

    result = summarize_grid_model_input_from_oracle(connection)

    assert result["rows"] == 847_392
    assert result["target_population_15plus"] == 545_692
    assert result["duplicate_keys"] == 0
    assert "COUNT(*)" in connection.cursor_instance.query
    assert "VW_GRID_TARGET_MODEL_INPUT" in connection.cursor_instance.query


def test_summary_rejects_empty_model_input() -> None:
    connection = _FakeConnection((0,) + (0,) * 12)

    try:
        summarize_grid_model_input_from_oracle(connection)
    except ValueError as exc:
        assert "ETL 결과가 없습니다" in str(exc)
    else:
        raise AssertionError("빈 모델 입력은 ValueError여야 합니다.")


def test_local_grid_model_input_matches_existing_shape_and_total() -> None:
    frame = load_grid_model_input_from_local(PROJECT_ROOT)

    assert len(frame) == 847_392
    assert frame["GRID_CD"].nunique() == 60_528
    assert int(frame["target_population_est"].sum()) == 545_692
    assert not frame.duplicated(["GRID_CD", "sex_code", "model_age_code"]).any()


def test_grid_model_input_dispatch_requires_oracle_connection() -> None:
    with pytest.raises(ValueError, match="oracle_connection"):
        load_grid_model_input(backend="oracle", project_root=PROJECT_ROOT)


def test_grid_model_input_dispatch_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="local 또는 oracle"):
        load_grid_model_input(backend="cloud", project_root=PROJECT_ROOT)
