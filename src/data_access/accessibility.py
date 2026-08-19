"""기존 H3SFCA 산출물을 변경 없이 Oracle 적재 형태로 검증·변환한다."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.data_access.card_usage import MIDDLE_CATEGORY_CODES, MIDDLE_SCHEME
from src.data_access.oracle_validation import compare_keyed_numeric_frames


PIPELINE_NAME = "h3sfca_accessibility_baseline_v1"
METHOD_CODE = "H3SFCA_GAUSSIAN_HUFF_V1"
DEMAND_BASIS = "TARGET_POPULATION_UNWEIGHTED"
TARGET_REFERENCE_YEAR = 2024
MERCHANT_SNAPSHOT_DATE = date(2026, 7, 6)

ACCESS_MODE_CODES = {"도보": "WALK", "대중교통": "TRANSIT"}
CATEGORIES_BY_MODE = {
    "도보": {"도서", "문화체험", "음악", "영상", "체육시설", "체육용품"},
    "대중교통": {"공연", "관광지", "미술", "스포츠관람"},
}

EXPECTED_ROWS = {
    "grid_accessibility": 304_509,
    "facility_ratio": 4_282,
    "grid_summary": 94_930,
    "dong_summary": 3_685,
    "category_summary": 10,
}

GRID_COLUMNS = [
    "target_reference_year",
    "merchant_snapshot_date",
    "method_code",
    "demand_basis",
    "access_mode_code",
    "grid_cd",
    "scheme_code",
    "category_code",
    "accessibility_score",
    "accessible_merchant_count",
    "target_population_est",
]

FACILITY_COLUMNS = [
    "target_reference_year",
    "merchant_snapshot_date",
    "method_code",
    "demand_basis",
    "access_mode_code",
    "merchant_source_id",
    "scheme_code",
    "category_code",
    "effective_demand",
    "facility_name",
    "district_name",
    "subcategory_name",
    "supply_quantity",
    "supply_demand_ratio",
]


def _read_csv(path: str | Path) -> pd.DataFrame:
    resolved = Path(path)
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise FileNotFoundError(f"H3SFCA 산출물이 없거나 비어 있습니다: {resolved}")
    return pd.read_csv(resolved, encoding="utf-8-sig", low_memory=False)


def _require_columns(frame: pd.DataFrame, required: set[str], context: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{context} 필수 열이 없습니다: {missing}")


def _validate_key(frame: pd.DataFrame, keys: list[str], context: str) -> None:
    if frame[keys].isna().any().any():
        raise ValueError(f"{context} 키에 결측이 있습니다: {keys}")
    if frame.duplicated(keys).any():
        raise ValueError(f"{context} 키가 중복됩니다: {keys}")


def _validate_nonnegative(
    frame: pd.DataFrame,
    columns: list[str],
    context: str,
) -> None:
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    values = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError(f"{context} 수치열에 결측·무한대·음수가 있습니다: {columns}")


def _validate_mode_category_contract(frame: pd.DataFrame) -> None:
    actual_modes = set(frame["접근수단"].astype(str))
    if actual_modes != set(CATEGORIES_BY_MODE):
        raise ValueError(f"H3SFCA 접근수단이 다릅니다: {sorted(actual_modes)}")
    for mode, expected_categories in CATEGORIES_BY_MODE.items():
        actual_categories = set(
            frame.loc[frame["접근수단"].eq(mode), "중분류"].astype(str)
        )
        if actual_categories != expected_categories:
            raise ValueError(
                f"{mode} H3SFCA 중분류가 다릅니다: {sorted(actual_categories)}"
            )


def load_grid_accessibility(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """기존 격자×접근수단×중분류 결과를 검증하고 적재형으로 변환한다."""

    raw = _read_csv(path)
    required = {
        "접근수단",
        "GRID_CD",
        "중분류",
        "H3SFCA_접근성",
        "접근가능_가맹점수",
        "시군구_격자",
        "행정동_격자",
        "문화누리대상자_추정_인구수",
    }
    _require_columns(raw, required, "격자 H3SFCA")
    if len(raw) != EXPECTED_ROWS["grid_accessibility"]:
        raise ValueError(
            "격자 H3SFCA 행 수가 기존 결과와 다릅니다: "
            f"actual={len(raw):,}, expected={EXPECTED_ROWS['grid_accessibility']:,}"
        )
    _validate_key(raw, ["접근수단", "GRID_CD", "중분류"], "격자 H3SFCA")
    _validate_nonnegative(
        raw,
        ["H3SFCA_접근성", "접근가능_가맹점수", "문화누리대상자_추정_인구수"],
        "격자 H3SFCA",
    )
    _validate_mode_category_contract(raw)
    if raw["GRID_CD"].nunique() != 56_496:
        raise ValueError("격자 H3SFCA의 고유 격자 수가 56,496개가 아닙니다.")
    if raw["시군구_격자"].nunique() != 25:
        raise ValueError("격자 H3SFCA의 자치구 수가 25개가 아닙니다.")
    if raw[["시군구_격자", "행정동_격자"]].drop_duplicates().shape[0] != 426:
        raise ValueError("격자 H3SFCA의 행정동 수가 426개가 아닙니다.")

    category_codes = raw["중분류"].map(MIDDLE_CATEGORY_CODES)
    if category_codes.isna().any():
        missing = sorted(raw.loc[category_codes.isna(), "중분류"].unique())
        raise ValueError(f"공급 13중분류 코드가 없는 H3SFCA 분야입니다: {missing}")

    result = pd.DataFrame(
        {
            "target_reference_year": TARGET_REFERENCE_YEAR,
            "merchant_snapshot_date": MERCHANT_SNAPSHOT_DATE,
            "method_code": METHOD_CODE,
            "demand_basis": DEMAND_BASIS,
            "access_mode_code": raw["접근수단"].map(ACCESS_MODE_CODES),
            "grid_cd": raw["GRID_CD"].astype("string"),
            "scheme_code": MIDDLE_SCHEME,
            "category_code": category_codes,
            "accessibility_score": raw["H3SFCA_접근성"].astype(float),
            "accessible_merchant_count": raw["접근가능_가맹점수"].astype("int64"),
            "target_population_est": raw[
                "문화누리대상자_추정_인구수"
            ].astype(float),
        }
    )
    return result[GRID_COLUMNS].reset_index(drop=True), raw


def load_facility_ratio(path: str | Path) -> pd.DataFrame:
    """기존 가맹점 공급수요비 결과를 검증하고 적재형으로 변환한다."""

    raw = _read_csv(path)
    required = {
        "접근수단",
        "가맹점_ID",
        "중분류",
        "시설_유효수요",
        "가맹점명",
        "시군구_가맹점",
        "소분류",
        "공급량",
        "시설_공급수요비",
    }
    _require_columns(raw, required, "가맹점 공급수요비")
    if len(raw) != EXPECTED_ROWS["facility_ratio"]:
        raise ValueError(
            "가맹점 공급수요비 행 수가 기존 결과와 다릅니다: "
            f"actual={len(raw):,}, expected={EXPECTED_ROWS['facility_ratio']:,}"
        )
    _validate_key(raw, ["접근수단", "가맹점_ID", "중분류"], "가맹점 공급수요비")
    _validate_nonnegative(
        raw,
        ["시설_유효수요", "공급량", "시설_공급수요비"],
        "가맹점 공급수요비",
    )
    _validate_mode_category_contract(raw)
    text_columns = ["가맹점명", "시군구_가맹점", "소분류"]
    if raw[text_columns].isna().any().any():
        raise ValueError("가맹점 공급수요비의 이름·지역·소분류에 결측이 있습니다.")

    category_codes = raw["중분류"].map(MIDDLE_CATEGORY_CODES)
    result = pd.DataFrame(
        {
            "target_reference_year": TARGET_REFERENCE_YEAR,
            "merchant_snapshot_date": MERCHANT_SNAPSHOT_DATE,
            "method_code": METHOD_CODE,
            "demand_basis": DEMAND_BASIS,
            "access_mode_code": raw["접근수단"].map(ACCESS_MODE_CODES),
            "merchant_source_id": raw["가맹점_ID"].astype("string"),
            "scheme_code": MIDDLE_SCHEME,
            "category_code": category_codes,
            "effective_demand": raw["시설_유효수요"].astype(float),
            "facility_name": raw["가맹점명"].astype("string"),
            "district_name": raw["시군구_가맹점"].astype("string"),
            "subcategory_name": raw["소분류"].astype("string"),
            "supply_quantity": raw["공급량"].astype(float),
            "supply_demand_ratio": raw["시설_공급수요비"].astype(float),
        }
    )
    return result[FACILITY_COLUMNS].reset_index(drop=True)


def _summary_check(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    keys: list[str],
    numeric: list[str],
    context: str,
) -> dict[str, object]:
    return compare_keyed_numeric_frames(
        expected,
        actual,
        key_columns=keys,
        numeric_columns=numeric,
        context=context,
        absolute_tolerances={column: 1e-12 for column in numeric},
    )


def validate_saved_summaries(
    grid_raw: pd.DataFrame,
    *,
    grid_summary_path: str | Path,
    dong_summary_path: str | Path,
    category_summary_path: str | Path,
) -> list[dict[str, object]]:
    """기존 노트북 산식으로 세 요약 CSV가 원 격자 결과와 같은지 확인한다."""

    category_expected = (
        grid_raw.groupby(["접근수단", "중분류"], as_index=False)
        .agg(
            격자수=("GRID_CD", "nunique"),
            평균_H3SFCA=("H3SFCA_접근성", "mean"),
            중앙값_H3SFCA=("H3SFCA_접근성", "median"),
            하위10퍼센트=("H3SFCA_접근성", lambda values: values.quantile(0.1)),
            상위90퍼센트=("H3SFCA_접근성", lambda values: values.quantile(0.9)),
            평균_접근가능가맹점수=("접근가능_가맹점수", "mean"),
        )
    )
    grid_expected = grid_raw.groupby(["접근수단", "GRID_CD"], as_index=False).agg(
        평균_H3SFCA=("H3SFCA_접근성", "mean"),
        최저_H3SFCA=("H3SFCA_접근성", "min"),
        접근가능_중분류수=("중분류", "nunique"),
        평균_접근가능가맹점수=("접근가능_가맹점수", "mean"),
        시군구_격자=("시군구_격자", "first"),
        행정동_격자=("행정동_격자", "first"),
        문화누리대상자_추정_인구수=("문화누리대상자_추정_인구수", "first"),
    )
    dong_expected = grid_raw.groupby(
        ["접근수단", "시군구_격자", "행정동_격자", "중분류"], as_index=False
    ).agg(
        평균_H3SFCA=("H3SFCA_접근성", "mean"),
        중앙값_H3SFCA=("H3SFCA_접근성", "median"),
        격자수=("GRID_CD", "nunique"),
        평균_접근가능가맹점수=("접근가능_가맹점수", "mean"),
    )

    actual_grid = _read_csv(grid_summary_path)
    actual_dong = _read_csv(dong_summary_path)
    actual_category = _read_csv(category_summary_path)
    expected_sizes = {
        "grid_summary": len(actual_grid),
        "dong_summary": len(actual_dong),
        "category_summary": len(actual_category),
    }
    for name, actual_size in expected_sizes.items():
        if actual_size != EXPECTED_ROWS[name]:
            raise ValueError(
                f"{name} 행 수가 다릅니다: actual={actual_size:,}, "
                f"expected={EXPECTED_ROWS[name]:,}"
            )

    grid_labels = grid_expected.merge(
        actual_grid,
        on=["접근수단", "GRID_CD"],
        how="outer",
        validate="1:1",
        suffixes=("_expected", "_actual"),
        indicator=True,
    )
    label_mismatches = int(
        grid_labels["_merge"].ne("both").sum()
        + grid_labels["시군구_격자_expected"]
        .ne(grid_labels["시군구_격자_actual"])
        .sum()
        + grid_labels["행정동_격자_expected"]
        .ne(grid_labels["행정동_격자_actual"])
        .sum()
    )
    if label_mismatches:
        raise ValueError(f"격자 요약의 자치구·행정동 값이 다릅니다: {label_mismatches}")

    return [
        _summary_check(
            grid_expected,
            actual_grid,
            keys=["접근수단", "GRID_CD"],
            numeric=[
                "평균_H3SFCA",
                "최저_H3SFCA",
                "접근가능_중분류수",
                "평균_접근가능가맹점수",
                "문화누리대상자_추정_인구수",
            ],
            context="기존 H3SFCA 격자 요약",
        ),
        _summary_check(
            dong_expected,
            actual_dong,
            keys=["접근수단", "시군구_격자", "행정동_격자", "중분류"],
            numeric=[
                "평균_H3SFCA",
                "중앙값_H3SFCA",
                "격자수",
                "평균_접근가능가맹점수",
            ],
            context="기존 H3SFCA 행정동 요약",
        ),
        _summary_check(
            category_expected,
            actual_category,
            keys=["접근수단", "중분류"],
            numeric=[
                "격자수",
                "평균_H3SFCA",
                "중앙값_H3SFCA",
                "하위10퍼센트",
                "상위90퍼센트",
                "평균_접근가능가맹점수",
            ],
            context="기존 H3SFCA 중분류 요약",
        ),
    ]


def prepare_h3sfca_baseline_for_oracle(
    *,
    grid_accessibility_path: str | Path,
    facility_ratio_path: str | Path,
    grid_summary_path: str | Path,
    dong_summary_path: str | Path,
    category_summary_path: str | Path,
) -> dict[str, Any]:
    grid, grid_raw = load_grid_accessibility(grid_accessibility_path)
    facility = load_facility_ratio(facility_ratio_path)
    summary_checks = validate_saved_summaries(
        grid_raw,
        grid_summary_path=grid_summary_path,
        dong_summary_path=dong_summary_path,
        category_summary_path=category_summary_path,
    )
    if not all(bool(check["passed"]) for check in summary_checks):
        failed = [check["context"] for check in summary_checks if not check["passed"]]
        raise ValueError(f"기존 H3SFCA 요약값이 원 격자 결과와 다릅니다: {failed}")
    return {
        "grid": grid,
        "facility": facility,
        "summary_checks": summary_checks,
    }


def _oracle_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def iter_frame_records(
    frame: pd.DataFrame,
    *,
    etl_run_id: int,
    chunk_size: int = 10_000,
) -> Iterable[list[dict[str, Any]]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")
    columns = list(frame.columns)
    for start in range(0, len(frame), chunk_size):
        chunk = frame.iloc[start : start + chunk_size]
        yield [
            {
                "etl_run_id": etl_run_id,
                **{
                    column: _oracle_value(value)
                    for column, value in zip(columns, row, strict=True)
                },
            }
            for row in chunk.itertuples(index=False, name=None)
        ]


# ---------------------------------------------------------------------------
# 기존 local/Oracle 조회 호환 계층
# ---------------------------------------------------------------------------

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd



GRID_ACCESSIBILITY_COLUMNS = [
    "접근수단",
    "GRID_CD",
    "중분류",
    "H3SFCA_접근성",
    "접근가능_가맹점수",
    "시군구_격자",
    "행정동_격자",
    "문화누리대상자_추정_인구수",
]

FACILITY_RATIO_COLUMNS = [
    "접근수단",
    "가맹점_ID",
    "중분류",
    "시설_유효수요",
    "가맹점명",
    "시군구_가맹점",
    "소분류",
    "공급량",
    "시설_공급수요비",
]

MODE_NAMES = {code: name for name, code in ACCESS_MODE_CODES.items()}


def _validate_frames(
    grid: pd.DataFrame,
    facility: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    for context, frame, columns in (
        ("격자 H3SFCA", grid, GRID_ACCESSIBILITY_COLUMNS),
        ("가맹점 공급수요비", facility, FACILITY_RATIO_COLUMNS),
    ):
        missing = sorted(set(columns) - set(frame.columns))
        if missing:
            raise ValueError(f"{context} 필수 열이 없습니다: {missing}")
        if frame[columns].isna().any().any():
            raise ValueError(f"{context} 필수 열에 결측이 있습니다.")

    if len(grid) != EXPECTED_ROWS["grid_accessibility"]:
        raise ValueError(f"격자 H3SFCA 행 수가 다릅니다: {len(grid):,}")
    if len(facility) != EXPECTED_ROWS["facility_ratio"]:
        raise ValueError(f"가맹점 공급수요비 행 수가 다릅니다: {len(facility):,}")
    if grid.duplicated(["접근수단", "GRID_CD", "중분류"]).any():
        raise ValueError("격자 H3SFCA 키가 중복됩니다.")
    if facility.duplicated(["접근수단", "가맹점_ID", "중분류"]).any():
        raise ValueError("가맹점 공급수요비 키가 중복됩니다.")

    numeric_grid = [
        "H3SFCA_접근성",
        "접근가능_가맹점수",
        "문화누리대상자_추정_인구수",
    ]
    numeric_facility = ["시설_유효수요", "공급량", "시설_공급수요비"]
    for frame, columns, context in (
        (grid, numeric_grid, "격자 H3SFCA"),
        (facility, numeric_facility, "가맹점 공급수요비"),
    ):
        frame[columns] = frame[columns].apply(pd.to_numeric, errors="raise")
        values = frame[columns].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f"{context} 수치열에 무한대 또는 음수가 있습니다.")

    for mode, expected_categories in CATEGORIES_BY_MODE.items():
        actual = set(grid.loc[grid["접근수단"].eq(mode), "중분류"].astype(str))
        if actual != expected_categories:
            raise ValueError(f"{mode} H3SFCA 중분류 구성이 다릅니다: {sorted(actual)}")
    return (
        grid[GRID_ACCESSIBILITY_COLUMNS].reset_index(drop=True),
        facility[FACILITY_RATIO_COLUMNS].reset_index(drop=True),
    )


def load_accessibility_from_local(
    project_root: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """기존 로컬 CSV 두 개를 원래 컬럼 형식으로 읽는다."""

    output_dir = Path(project_root) / "notebooks/access/OUTPUT/h3sfca"
    grid = pd.read_csv(
        output_dir / "h3sfca_격자_중분류_접근성.csv",
        encoding="utf-8-sig",
        low_memory=False,
    )
    facility = pd.read_csv(
        output_dir / "h3sfca_가맹점_공급수요비.csv",
        encoding="utf-8-sig",
        low_memory=False,
    )
    return _validate_frames(grid, facility)


def _latest_run_id(cursor: Any) -> int:
    cursor.execute(
        """
        SELECT etl_run_id FROM META_ETL_RUN
        WHERE pipeline_name = :pipeline_name AND status = 'SUCCESS'
        ORDER BY etl_run_id DESC FETCH FIRST 1 ROW ONLY
        """,
        pipeline_name=PIPELINE_NAME,
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError("Oracle에 성공한 H3SFCA baseline_v1 ETL 실행이 없습니다.")
    return int(row[0])


def load_accessibility_from_oracle(
    connection: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Oracle 결과를 기존 H3SFCA CSV와 같은 한글 컬럼으로 복원한다."""

    with connection.cursor() as cursor:
        cursor.arraysize = 10_000
        run_id = _latest_run_id(cursor)
        cursor.execute(
            """
            SELECT access_mode_name, grid_cd, category_name,
                   accessibility_score, accessible_merchant_count,
                   district_name, dong_name, target_population_est
            FROM VW_GRID_ACCESSIBILITY
            WHERE etl_run_id = :run_id
            """,
            run_id=run_id,
        )
        grid = pd.DataFrame(cursor.fetchall(), columns=GRID_ACCESSIBILITY_COLUMNS)

        cursor.execute(
            """
            SELECT access_mode_code, merchant_source_id, c.category_name,
                   effective_demand, facility_name, district_name,
                   subcategory_name, supply_quantity, supply_demand_ratio
            FROM FACT_FACILITY_ACCESS_RATIO f
            JOIN DIM_CATEGORY c
              ON c.scheme_code = f.scheme_code
             AND c.category_code = f.category_code
            WHERE f.etl_run_id = :run_id
            """,
            run_id=run_id,
        )
        facility = pd.DataFrame(cursor.fetchall(), columns=FACILITY_RATIO_COLUMNS)
    facility["접근수단"] = facility["접근수단"].map(MODE_NAMES)
    if facility["접근수단"].isna().any():
        raise ValueError(
            "Oracle 가맹점 공급수요비에 알 수 없는 접근수단 코드가 있습니다."
        )
    return _validate_frames(grid, facility)


def load_accessibility_data(
    *,
    backend: str,
    project_root: str | Path,
    oracle_connection: Any | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """선택한 backend에서 기존 H3SFCA 상세 결과 두 개를 반환한다."""

    normalized = backend.strip().lower()
    if normalized == "local":
        return load_accessibility_from_local(project_root)
    if normalized == "oracle":
        if oracle_connection is None:
            raise ValueError("oracle backend에는 oracle_connection이 필요합니다.")
        return load_accessibility_from_oracle(oracle_connection)
    raise ValueError("backend는 local 또는 oracle이어야 합니다.")
