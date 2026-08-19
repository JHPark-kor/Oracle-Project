"""OCI data-access tests grouped by domain."""

from __future__ import annotations

# ---- consolidated from test_oci_config.py ----
from pathlib import Path

from src.data_access import OciSettings, OracleDbSettings


def test_defaults_target_tokyo_and_local_backend() -> None:
    settings = OciSettings.from_env({})

    assert settings.data_backend == "local"
    assert settings.auth == "security_token"
    assert settings.region == "ap-tokyo-1"
    assert settings.compartment_name == "mnc-project-dev"
    assert settings.raw_bucket == "mnc-raw-private"
    assert settings.artifact_bucket == "mnc-artifacts"
    assert settings.validation_errors() == []


def test_environment_values_are_normalized() -> None:
    settings = OciSettings.from_env(
        {
            "DATA_BACKEND": " ORACLE ",
            "OCI_CONFIG_FILE": "~/custom-oci-config",
            "OCI_PROFILE": "TEAM",
            "OCI_AUTH": " API_KEY ",
            "OCI_REGION": "ap-tokyo-1",
            "OCI_COMPARTMENT_NAME": "mnc-project-dev",
            "OCI_RAW_BUCKET": "mnc-raw-private",
            "OCI_ARTIFACT_BUCKET": "mnc-artifacts",
        }
    )

    assert settings.data_backend == "oracle"
    assert settings.config_file == Path("~/custom-oci-config").expanduser()
    assert settings.profile == "TEAM"
    assert settings.auth == "api_key"
    assert settings.validation_errors() == []


def test_invalid_backend_and_blank_resource_name_are_rejected() -> None:
    settings = OciSettings.from_env(
        {
            "DATA_BACKEND": "cloud",
            "OCI_AUTH": "password",
            "OCI_COMPARTMENT_NAME": "   ",
        }
    )

    errors = settings.validation_errors()
    assert any("DATA_BACKEND" in error for error in errors)
    assert any("OCI_AUTH" in error for error in errors)
    assert any("OCI_COMPARTMENT_NAME" in error for error in errors)


def test_database_settings_accept_complete_wallet(tmp_path: Path) -> None:
    wallet_dir = tmp_path / "wallet"
    wallet_dir.mkdir()
    for filename in ("tnsnames.ora", "sqlnet.ora", "ewallet.pem", "cwallet.sso"):
        (wallet_dir / filename).write_text("test", encoding="utf-8")

    settings = OracleDbSettings.from_env(
        {
            "ORACLE_DB_USER": "admin",
            "ORACLE_DB_DSN": "mncdev_low",
            "ORACLE_DB_WALLET_DIR": str(wallet_dir),
        }
    )

    assert settings.user == "ADMIN"
    assert settings.dsn == "mncdev_low"
    assert settings.wallet_dir == wallet_dir
    assert settings.validation_errors() == []


def test_database_settings_reject_missing_wallet_files(tmp_path: Path) -> None:
    wallet_dir = tmp_path / "wallet"
    wallet_dir.mkdir()
    (wallet_dir / "tnsnames.ora").write_text("test", encoding="utf-8")

    settings = OracleDbSettings.from_env(
        {
            "ORACLE_DB_USER": "ADMIN",
            "ORACLE_DB_DSN": "mncdev_low",
            "ORACLE_DB_WALLET_DIR": str(wallet_dir),
        }
    )

    errors = settings.validation_errors()
    assert any("sqlnet.ora" in error for error in errors)
    assert any("ewallet.pem" in error for error in errors)
    assert any("cwallet.sso" in error for error in errors)

# ---- consolidated from test_oci_upload_metadata.py ----
from urllib.parse import unquote

from scripts.upload_oci_raw_data import _object_metadata


def test_korean_source_name_is_safe_for_oci_http_metadata() -> None:
    source_name = "서울시_격자_100m_성연령별_인구수.csv"

    metadata = _object_metadata(source_name, "a" * 64, "2024")

    assert metadata["source-name"].isascii()
    assert unquote(metadata["source-name"]) == source_name
    assert metadata["source-name-encoding"] == "percent"
    assert all(
        value.encode("latin-1") is not None
        for value in metadata.values()
    )


def test_ascii_source_name_remains_readable() -> None:
    metadata = _object_metadata("grid_pop_access.csv", "b" * 64, "2024")

    assert metadata["source-name"] == "grid_pop_access.csv"

# ---- consolidated from test_oracle_schema.py ----
import pytest

from src.data_access.oracle_schema import (
    APP_SCHEMA,
    ETL_ROLE,
    READ_ROLE,
    TABLE_DDL,
    VIEW_DDL,
    bootstrap_plan,
    validate_app_password,
    validate_identifier,
)


def test_bootstrap_plan_has_unique_core_objects() -> None:
    plan = bootstrap_plan()

    assert plan["app_user"] == "MNC_APP"
    assert plan["roles"] == ["MNC_READ_ROLE", "MNC_ETL_ROLE"]
    assert len(plan["tables"]) == len(set(plan["tables"])) == 18
    assert plan["views"] == [
        "VW_CARD_GU_CAT",
        "VW_GRID_TARGET_MODEL_INPUT",
        "VW_GRID_PREF_DEMAND",
        "VW_DONG_PREF_DEMAND",
        "VW_GU_PREF_DEMAND",
        "VW_GRID_ACCESSIBILITY",
    ]
    assert "STG_CARD_USAGE_RAW27" in plan["tables"]
    assert "FACT_CARD_GU_CAT" in plan["tables"]
    assert "FACT_CARD_GU_SEX" in plan["tables"]
    assert "FACT_CARD_GU_AGE" in plan["tables"]
    assert "DIM_MERCHANT_SNAPSHOT" in plan["tables"]
    assert "DIM_GRID" in plan["tables"]
    assert "FACT_GRID_TARGET_SEX_AGE" in plan["tables"]
    assert "FACT_PREF_SEX_AGE" in plan["tables"]
    assert "FACT_GRID_PREF_DEMAND" in plan["tables"]
    assert "FACT_GRID_ACCESSIBILITY" in plan["tables"]
    assert "FACT_FACILITY_ACCESS_RATIO" in plan["tables"]


def test_all_object_identifiers_are_valid_and_short() -> None:
    names = [APP_SCHEMA, READ_ROLE, ETL_ROLE, *TABLE_DDL, *VIEW_DDL]

    assert [validate_identifier(name) for name in names] == names
    assert all(len(name) <= 30 for name in names)


@pytest.mark.parametrize(
    "value",
    ["mnc app", "1MNC", "MNC-APP", "A" * 31, "MNC_APP; DROP USER ADMIN"],
)
def test_invalid_oracle_identifiers_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_identifier(value)


def test_app_password_policy_accepts_valid_value() -> None:
    validate_app_password("CloudSafe2026!")


@pytest.mark.parametrize(
    "password",
    [
        "Short1!",
        "NOLOWERCASE2026!",
        "nouppercase2026!",
        "NoNumberPassword!",
        "Contains Space2026!",
        'Contains"Quote2026!',
        "Mnc_AppSecure2026!",
    ],
)
def test_app_password_policy_rejects_unsafe_values(password: str) -> None:
    with pytest.raises(ValueError):
        validate_app_password(password)


def test_schema_contains_primary_keys_and_nonnegative_checks() -> None:
    assert "PRIMARY KEY" in TABLE_DDL["META_SOURCE_FILE"]
    assert "PRIMARY KEY" in TABLE_DDL["FACT_CARD_GU_YEAR"]
    assert "usage_amount_won >= 0" in TABLE_DDL["STG_CARD_USAGE_RAW27"]
    assert "usage_count >= 0" in TABLE_DDL["FACT_CARD_GU_CAT"]
    assert "etl_run_id, merchant_key" in TABLE_DDL["DIM_MERCHANT_SNAPSHOT"]
    assert "etl_run_id, grid_cd, sex_code, aligned_age_order" in TABLE_DDL[
        "FACT_GRID_TARGET_SEX_AGE"
    ]
    assert "target_population_est >= 0" in TABLE_DDL[
        "FACT_GRID_TARGET_SEX_AGE"
    ]
    assert "absolute_probability BETWEEN 0 AND 1" in TABLE_DDL[
        "FACT_PREF_SEX_AGE"
    ]
    assert "etl_run_id, grid_cd, category_code" in TABLE_DDL[
        "FACT_GRID_PREF_DEMAND"
    ]
    assert "etl_run_id, access_mode_code, grid_cd, category_code" in TABLE_DDL[
        "FACT_GRID_ACCESSIBILITY"
    ]
    assert "demand_basis = 'TARGET_POPULATION_UNWEIGHTED'" in TABLE_DDL[
        "FACT_GRID_ACCESSIBILITY"
    ]

# ---- consolidated from test_oracle_validation.py ----
import pandas as pd
import pytest

from src.data_access.oracle_validation import compare_keyed_numeric_frames


def test_compare_frames_ignores_row_order_when_values_match() -> None:
    local = pd.DataFrame(
        {"key": ["A", "B"], "amount": [10, 20], "count": [1, 2]}
    )
    oracle = local.iloc[::-1].reset_index(drop=True)

    result = compare_keyed_numeric_frames(
        local,
        oracle,
        key_columns=["key"],
        numeric_columns=["amount", "count"],
        context="test",
    )

    assert result["passed"] is True
    assert result["numeric_mismatch_rows"] == 0


def test_compare_frames_reports_missing_and_changed_values() -> None:
    local = pd.DataFrame({"key": ["A", "B"], "amount": [10, 20]})
    oracle = pd.DataFrame({"key": ["A", "C"], "amount": [11, 30]})

    result = compare_keyed_numeric_frames(
        local,
        oracle,
        key_columns=["key"],
        numeric_columns=["amount"],
        context="test",
    )

    assert result["passed"] is False
    assert result["missing_from_local"] == 1
    assert result["missing_from_oracle"] == 1
    assert result["numeric_mismatch_rows"] == 3


def test_compare_frames_allows_only_explicit_float_tolerance() -> None:
    local = pd.DataFrame({"key": ["A"], "rate": [8.449999999999998]})
    oracle = pd.DataFrame({"key": ["A"], "rate": [8.45]})

    exact = compare_keyed_numeric_frames(
        local,
        oracle,
        key_columns=["key"],
        numeric_columns=["rate"],
        context="test",
    )
    tolerant = compare_keyed_numeric_frames(
        local,
        oracle,
        key_columns=["key"],
        numeric_columns=["rate"],
        context="test",
        absolute_tolerances={"rate": 1e-8},
    )

    assert exact["passed"] is False
    assert tolerant["passed"] is True
    assert tolerant["numeric_mismatch_by_column"]["rate"] == 0


def test_compare_frames_treats_two_nulls_as_equal() -> None:
    local = pd.DataFrame({"key": ["A"], "amount": [None]})
    oracle = pd.DataFrame({"key": ["A"], "amount": [None]})

    result = compare_keyed_numeric_frames(
        local,
        oracle,
        key_columns=["key"],
        numeric_columns=["amount"],
        context="test",
    )

    assert result["passed"] is True


def test_compare_frames_rejects_duplicate_keys() -> None:
    duplicate = pd.DataFrame({"key": ["A", "A"], "amount": [10, 10]})

    with pytest.raises(ValueError, match="중복 키"):
        compare_keyed_numeric_frames(
            duplicate,
            duplicate.iloc[:1],
            key_columns=["key"],
            numeric_columns=["amount"],
            context="test",
        )

# ---- consolidated from test_project_readiness.py ----
from src.data_access.project_readiness import (
    EXPECTED_COUNTS,
    PIPELINES,
    REQUIRED_OBJECTS,
    evaluate_readiness,
)


def test_complete_project_readiness_passes() -> None:
    result = evaluate_readiness(
        run_ids={name: index for index, name in enumerate(PIPELINES, start=1)},
        counts=EXPECTED_COUNTS,
        existing_objects=set(REQUIRED_OBJECTS),
        accessibility_methods={"H3SFCA_GAUSSIAN_HUFF_V1"},
        accessibility_demand_bases={"TARGET_POPULATION_UNWEIGHTED"},
    )

    assert result["all_checks_passed"] is True
    assert result["passed"] == result["total"]


def test_project_readiness_reports_missing_pipeline_and_wrong_count() -> None:
    run_ids = {name: index for index, name in enumerate(PIPELINES, start=1)}
    run_ids["accessibility"] = None
    counts = dict(EXPECTED_COUNTS)
    counts["accessibility_grid"] = 0

    result = evaluate_readiness(
        run_ids=run_ids,
        counts=counts,
        existing_objects=set(REQUIRED_OBJECTS) - {"VW_GRID_ACCESSIBILITY"},
        accessibility_methods=set(),
        accessibility_demand_bases=set(),
    )

    assert result["all_checks_passed"] is False
    failed = {check["check"] for check in result["checks"] if not check["passed"]}
    assert "latest_success_run_accessibility" in failed
    assert "row_count_accessibility_grid" in failed
    assert "required_oracle_objects" in failed


def test_project_readiness_rejects_unexpected_accessibility_definition() -> None:
    result = evaluate_readiness(
        run_ids={name: index for index, name in enumerate(PIPELINES, start=1)},
        counts=EXPECTED_COUNTS,
        existing_objects=set(REQUIRED_OBJECTS),
        accessibility_methods={"H3SFCA_GAUSSIAN_HUFF_V1", "NEW_METHOD"},
        accessibility_demand_bases={"PREFERENCE_WEIGHTED"},
    )

    failed = {check["check"] for check in result["checks"] if not check["passed"]}
    assert "accessibility_method_is_single_baseline" in failed
    assert "accessibility_demand_basis_is_unweighted" in failed
