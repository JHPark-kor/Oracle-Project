"""MNCDEV에 이전한 프로젝트 데이터의 최신 성공 실행과 행 수를 점검한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.data_access.accessibility import (
    DEMAND_BASIS,
    METHOD_CODE,
    PIPELINE_NAME as ACCESS_PIPELINE,
)
from src.data_access.card_usage import PIPELINE_NAME as CARD_PIPELINE
from src.data_access.grid_population import PIPELINE_NAME as GRID_PIPELINE
from src.data_access.merchant import PIPELINE_NAME as MERCHANT_PIPELINE
from src.data_access.preference import PIPELINE_NAME as PREFERENCE_PIPELINE


PIPELINES = {
    "card": CARD_PIPELINE,
    "merchant": MERCHANT_PIPELINE,
    "grid_population": GRID_PIPELINE,
    "preference": PREFERENCE_PIPELINE,
    "accessibility": ACCESS_PIPELINE,
}

COUNT_QUERIES = {
    "card_raw27": (
        "SELECT COUNT(*) FROM STG_CARD_USAGE_RAW27 WHERE etl_run_id = :run_id",
        "card",
    ),
    "card_gu_year": (
        "SELECT COUNT(*) FROM FACT_CARD_GU_YEAR WHERE etl_run_id = :run_id",
        "card",
    ),
    "card_gu_category": (
        "SELECT COUNT(*) FROM FACT_CARD_GU_CAT WHERE etl_run_id = :run_id",
        "card",
    ),
    "card_gu_sex": (
        "SELECT COUNT(*) FROM FACT_CARD_GU_SEX WHERE etl_run_id = :run_id",
        "card",
    ),
    "card_gu_age": (
        "SELECT COUNT(*) FROM FACT_CARD_GU_AGE WHERE etl_run_id = :run_id",
        "card",
    ),
    "merchant": (
        "SELECT COUNT(*) FROM DIM_MERCHANT_SNAPSHOT WHERE etl_run_id = :run_id",
        "merchant",
    ),
    "grid_target_aligned": (
        "SELECT COUNT(*) FROM FACT_GRID_TARGET_SEX_AGE WHERE etl_run_id = :run_id",
        "grid_population",
    ),
    "grid_target_model_input": (
        "SELECT COUNT(*) FROM VW_GRID_TARGET_MODEL_INPUT",
        None,
    ),
    "preference_probability": (
        "SELECT COUNT(*) FROM FACT_PREF_SEX_AGE WHERE etl_run_id = :run_id",
        "preference",
    ),
    "preference_grid_demand": (
        "SELECT COUNT(*) FROM FACT_GRID_PREF_DEMAND WHERE etl_run_id = :run_id",
        "preference",
    ),
    "accessibility_grid": (
        "SELECT COUNT(*) FROM FACT_GRID_ACCESSIBILITY WHERE etl_run_id = :run_id",
        "accessibility",
    ),
    "accessibility_facility": (
        "SELECT COUNT(*) FROM FACT_FACILITY_ACCESS_RATIO WHERE etl_run_id = :run_id",
        "accessibility",
    ),
}

EXPECTED_COUNTS = {
    "card_raw27": 3_375,
    "card_gu_year": 125,
    "card_gu_category": 1_625,
    "card_gu_sex": 250,
    "card_gu_age": 1_375,
    "merchant": 4_722,
    "grid_target_aligned": 1_089_504,
    "grid_target_model_input": 847_392,
    "preference_probability": 126,
    "preference_grid_demand": 484_224,
    "accessibility_grid": 304_509,
    "accessibility_facility": 4_282,
}

REQUIRED_OBJECTS = {
    "META_SOURCE_FILE",
    "META_ETL_RUN",
    "META_ETL_RUN_INPUT",
    "DIM_ADMIN_AREA",
    "DIM_GRID",
    "DIM_CATEGORY",
    "BRIDGE_CATEGORY_MAP",
    "STG_CARD_USAGE_RAW27",
    "FACT_CARD_GU_YEAR",
    "FACT_CARD_GU_CAT",
    "FACT_CARD_GU_SEX",
    "FACT_CARD_GU_AGE",
    "DIM_MERCHANT_SNAPSHOT",
    "FACT_GRID_TARGET_SEX_AGE",
    "FACT_PREF_SEX_AGE",
    "FACT_GRID_PREF_DEMAND",
    "FACT_GRID_ACCESSIBILITY",
    "FACT_FACILITY_ACCESS_RATIO",
    "VW_CARD_GU_CAT",
    "VW_GRID_TARGET_MODEL_INPUT",
    "VW_GRID_PREF_DEMAND",
    "VW_DONG_PREF_DEMAND",
    "VW_GU_PREF_DEMAND",
    "VW_GRID_ACCESSIBILITY",
}


def evaluate_readiness(
    *,
    run_ids: Mapping[str, int | None],
    counts: Mapping[str, int],
    existing_objects: set[str],
    accessibility_methods: set[str],
    accessibility_demand_bases: set[str],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for name, pipeline in PIPELINES.items():
        run_id = run_ids.get(name)
        checks.append(
            {
                "check": f"latest_success_run_{name}",
                "actual": run_id,
                "expected": "성공 실행 ID",
                "pipeline_name": pipeline,
                "passed": run_id is not None,
            }
        )
    for name, expected in EXPECTED_COUNTS.items():
        actual = counts.get(name)
        checks.append(
            {
                "check": f"row_count_{name}",
                "actual": actual,
                "expected": expected,
                "passed": actual == expected,
            }
        )
    missing_objects = sorted(REQUIRED_OBJECTS - existing_objects)
    checks.extend(
        [
            {
                "check": "required_oracle_objects",
                "actual": len(existing_objects & REQUIRED_OBJECTS),
                "expected": len(REQUIRED_OBJECTS),
                "missing": missing_objects,
                "passed": not missing_objects,
            },
            {
                "check": "accessibility_method_is_single_baseline",
                "actual": sorted(accessibility_methods),
                "expected": [METHOD_CODE],
                "passed": accessibility_methods == {METHOD_CODE},
            },
            {
                "check": "accessibility_demand_basis_is_unweighted",
                "actual": sorted(accessibility_demand_bases),
                "expected": [DEMAND_BASIS],
                "detail": "TARGET_POPULATION_UNWEIGHTED만 존재해야 함",
                "passed": accessibility_demand_bases == {DEMAND_BASIS},
            },
        ]
    )
    return {
        "checks": checks,
        "passed": sum(bool(check["passed"]) for check in checks),
        "total": len(checks),
        "all_checks_passed": all(bool(check["passed"]) for check in checks),
    }


def check_oracle_project_readiness(connection: Any) -> dict[str, Any]:
    """대용량 원행을 내려받지 않고 Oracle 내부 집계값만 확인한다."""

    run_ids: dict[str, int | None] = {}
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for name, pipeline in PIPELINES.items():
            cursor.execute(
                """
                SELECT etl_run_id FROM META_ETL_RUN
                WHERE pipeline_name = :pipeline_name AND status = 'SUCCESS'
                ORDER BY etl_run_id DESC FETCH FIRST 1 ROW ONLY
                """,
                pipeline_name=pipeline,
            )
            row = cursor.fetchone()
            run_ids[name] = int(row[0]) if row is not None else None

        for name, (query, pipeline_key) in COUNT_QUERIES.items():
            if pipeline_key is None:
                cursor.execute(query)
            else:
                run_id = run_ids[pipeline_key]
                if run_id is None:
                    counts[name] = -1
                    continue
                cursor.execute(query, run_id=run_id)
            counts[name] = int(cursor.fetchone()[0] or 0)

        object_binds = {f"o{index}": name for index, name in enumerate(REQUIRED_OBJECTS)}
        placeholders = ", ".join(f":{name}" for name in object_binds)
        cursor.execute(
            f"SELECT object_name FROM user_objects WHERE object_name IN ({placeholders})",
            **object_binds,
        )
        existing_objects = {str(row[0]) for row in cursor.fetchall()}

        access_run_id = run_ids["accessibility"]
        if access_run_id is None:
            methods: set[str] = set()
            demand_bases: set[str] = set()
        else:
            cursor.execute(
                """
                SELECT DISTINCT method_code, demand_basis
                FROM FACT_GRID_ACCESSIBILITY
                WHERE etl_run_id = :run_id
                """,
                run_id=access_run_id,
            )
            method_basis_rows = cursor.fetchall()
            methods = {str(row[0]) for row in method_basis_rows}
            demand_bases = {str(row[1]) for row in method_basis_rows}

    result = evaluate_readiness(
        run_ids=run_ids,
        counts=counts,
        existing_objects=existing_objects,
        accessibility_methods=methods,
        accessibility_demand_bases=demand_bases,
    )
    result.update({"latest_run_ids": run_ids, "row_counts": counts})
    return result
