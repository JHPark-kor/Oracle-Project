"""100m 격자와 성별·연령별 추정 대상자를 Oracle 적재 형태로 변환한다."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.data_access.card_usage import build_admin_area_rows
from src.preference_analysis.population_alignment import (
    ALIGNED_POPULATION_COLUMN,
    align_grid_sex_age_population,
)


PIPELINE_NAME = "grid_target_population_2024_v1"
REFERENCE_YEAR = 2024
EXPECTED_GRID_COUNT = 60_528
ESTIMATE_METHOD = (
    "기초생활수급자와 차상위계층 추정값의 단순합; "
    "자격군 간 중복을 조정하지 않은 정책대상자 proxy"
)

GRID_COLUMNS = [
    "GRID_CD",
    "행정동코드",
    "시군구",
    "행정동",
    "중심점_x",
    "중심점_y",
    "GRID_CD_500",
]

FACT_COLUMNS = [
    "reference_year",
    "grid_cd",
    "sex_code",
    "sex_label",
    "aligned_age_order",
    "aligned_age_group",
    "model_age_code",
    "model_age_label",
    "model_applicable",
    "alignment_status",
    "alignment_note",
    "source_age_groups",
    "source_age_group_count",
    "target_population_est",
    "proxy_flag",
    "overlap_adjusted",
    "estimate_method",
]


def _normalize_area_code(series: pd.Series, width: int) -> pd.Series:
    return (
        series.astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(width)
    )


def load_grid_lookup(
    grid_lookup_path: str | Path,
    *,
    expected_grid_count: int | None = EXPECTED_GRID_COUNT,
) -> pd.DataFrame:
    """접근성 열을 제외하고 격자 위치·행정구역 열만 검증해 읽는다."""

    frame = pd.read_csv(
        grid_lookup_path,
        usecols=GRID_COLUMNS,
        dtype={"GRID_CD": "string", "행정동코드": "string", "GRID_CD_500": "string"},
        low_memory=False,
    )
    if frame[GRID_COLUMNS].isna().any().any():
        raise ValueError("격자 lookup의 위치·행정구역 필수 열에 결측값이 있습니다.")
    frame["행정동코드"] = _normalize_area_code(frame["행정동코드"], 8)
    if frame["GRID_CD"].duplicated().any():
        raise ValueError("격자 lookup에 중복 GRID_CD가 있습니다.")
    if expected_grid_count is not None and len(frame) != expected_grid_count:
        raise ValueError(
            "격자 lookup 행 수가 기준과 다릅니다: "
            f"actual={len(frame):,}, expected={expected_grid_count:,}"
        )
    for column in ("중심점_x", "중심점_y"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise ValueError(f"격자 lookup의 {column}에 숫자 변환 실패가 있습니다.")
    if (~frame["행정동코드"].str.fullmatch(r"\d{8}")).any():
        raise ValueError("행정동코드는 8자리 숫자 문자열이어야 합니다.")

    stable = frame.groupby("행정동코드")[["시군구", "행정동"]].nunique()
    if stable.gt(1).any(axis=None):
        raise ValueError("하나의 행정동코드가 여러 지역명에 연결됩니다.")
    return frame.sort_values("GRID_CD").reset_index(drop=True)


def build_grid_admin_rows(
    grid_lookup: pd.DataFrame,
    grid_lookup_path: str | Path,
) -> list[dict[str, Any]]:
    """서울·자치구 기존 행에 426개 행정동 코드를 추가한다."""

    rows = build_admin_area_rows(grid_lookup_path)
    dongs = (
        grid_lookup[["행정동코드", "시군구", "행정동"]]
        .drop_duplicates()
        .sort_values("행정동코드")
    )
    if dongs["행정동코드"].duplicated().any():
        raise ValueError("행정동코드가 중복됩니다.")
    rows.extend(
        {
            "area_code": str(row.행정동코드),
            "area_name": str(row.행정동),
            "area_level": "DONG",
            "parent_area_code": str(row.행정동코드)[:5],
            "valid_from": date(2021, 1, 1),
            "source_reference_year": REFERENCE_YEAR,
        }
        for row in dongs.itertuples(index=False)
    )
    return rows


def build_grid_dimension_rows(grid_lookup: pd.DataFrame) -> list[dict[str, Any]]:
    """격자 위치 차원에 필요한 열만 추린다."""

    rows = [
        {
            "grid_cd": str(row.GRID_CD),
            "dong_code": str(row.행정동코드),
            "center_x": float(row.중심점_x),
            "center_y": float(row.중심점_y),
            "grid_cd_500": str(row.GRID_CD_500),
            "source_reference_year": REFERENCE_YEAR,
        }
        for row in grid_lookup.itertuples(index=False)
    ]
    if len(rows) != len({row["grid_cd"] for row in rows}):
        raise ValueError("격자 차원 키가 중복됩니다.")
    return rows


def build_target_fact_frame(aligned: pd.DataFrame) -> pd.DataFrame:
    """기존 연령 통일 결과를 원본 총량을 보존하는 Oracle fact로 만든다."""

    fact = pd.DataFrame(
        {
            "reference_year": REFERENCE_YEAR,
            "grid_cd": aligned["GRID_CD"].astype("string"),
            "sex_code": aligned["sex_code"].astype("int64"),
            "sex_label": aligned["성별"].astype("string"),
            "aligned_age_order": aligned["aligned_age_order"].astype("int64"),
            "aligned_age_group": aligned["aligned_age_group"].astype("string"),
            "model_age_code": aligned["model_age_code"].astype("Int64"),
            "model_age_label": aligned["model_age_label"].astype("string"),
            "model_applicable": aligned["preference_model_applicable"].map(
                {True: "Y", False: "N"}
            ),
            "alignment_status": aligned["alignment_status"].astype("string"),
            "alignment_note": aligned["alignment_note"].astype("string"),
            "source_age_groups": aligned["source_age_groups"].astype("string"),
            "source_age_group_count": aligned["source_age_group_count"].astype("int64"),
            "target_population_est": aligned[ALIGNED_POPULATION_COLUMN].astype("int64"),
            "proxy_flag": "Y",
            "overlap_adjusted": "N",
            "estimate_method": ESTIMATE_METHOD,
        }
    )
    keys = ["grid_cd", "sex_code", "aligned_age_order"]
    if fact.duplicated(keys).any():
        raise ValueError("격자×성별×통일연령 fact 키가 중복됩니다.")
    if (fact["target_population_est"] < 0).any():
        raise ValueError("격자 대상자 추정인구에 음수가 있습니다.")
    return fact[FACT_COLUMNS].sort_values(keys).reset_index(drop=True)


def prepare_grid_population_for_oracle(
    target_source_path: str | Path,
    grid_lookup_path: str | Path,
) -> dict[str, Any]:
    """기존 검증 정렬을 재사용해 격자·대상자 Oracle 입력을 만든다."""

    grid_lookup = load_grid_lookup(grid_lookup_path)
    source = pd.read_csv(target_source_path, encoding="utf-8-sig", low_memory=False)
    aligned, model_input, summary, validation = align_grid_sex_age_population(source)

    source_grids = set(source["GRID_CD"].astype("string"))
    lookup_grids = set(grid_lookup["GRID_CD"].astype("string"))
    if source_grids != lookup_grids:
        raise ValueError(
            "대상자 원본과 격자 lookup의 GRID_CD가 다릅니다: "
            f"source_only={len(source_grids - lookup_grids):,}, "
            f"lookup_only={len(lookup_grids - source_grids):,}"
        )

    source_location = source[["GRID_CD", "시군구", "행정동"]].drop_duplicates()
    lookup_location = grid_lookup[["GRID_CD", "시군구", "행정동"]]
    location_check = source_location.merge(
        lookup_location,
        on="GRID_CD",
        how="outer",
        suffixes=("_source", "_lookup"),
        indicator=True,
        validate="1:1",
    )
    location_mismatch = (
        location_check["_merge"].ne("both")
        | location_check["시군구_source"].ne(location_check["시군구_lookup"])
        | location_check["행정동_source"].ne(location_check["행정동_lookup"])
    )
    if location_mismatch.any():
        raise ValueError(
            "대상자 원본과 격자 lookup의 지역명이 다릅니다: "
            f"{int(location_mismatch.sum()):,}개"
        )

    fact = build_target_fact_frame(aligned)
    source_total = int(source["문화누리대상자_성연령별_추정_인구수"].sum())
    aligned_total = int(fact["target_population_est"].sum())
    model_total = int(
        fact.loc[fact["model_applicable"].eq("Y"), "target_population_est"].sum()
    )
    if source_total != aligned_total:
        raise RuntimeError("Oracle 적재 준비 중 대상자 총량이 변했습니다.")

    return {
        "source": source,
        "grid_lookup": grid_lookup,
        "admin_rows": build_grid_admin_rows(grid_lookup, grid_lookup_path),
        "grid_rows": build_grid_dimension_rows(grid_lookup),
        "aligned": aligned,
        "model_input": model_input,
        "fact": fact,
        "summary": summary,
        "validation": validation,
        "source_total": source_total,
        "aligned_total": aligned_total,
        "model_total": model_total,
    }


def iter_fact_records(
    fact: pd.DataFrame,
    *,
    etl_run_id: int,
    chunk_size: int = 10_000,
) -> Iterable[list[dict[str, Any]]]:
    """대용량 fact를 제한된 메모리의 Oracle executemany 묶음으로 변환한다."""

    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")
    for start in range(0, len(fact), chunk_size):
        chunk = fact.iloc[start : start + chunk_size]
        records: list[dict[str, Any]] = []
        for row in chunk.itertuples(index=False):
            values = row._asdict()
            model_age_code = values["model_age_code"]
            model_age_label = values["model_age_label"]
            records.append(
                {
                    **values,
                    "etl_run_id": etl_run_id,
                    "model_age_code": (
                        None if pd.isna(model_age_code) else int(model_age_code)
                    ),
                    "model_age_label": (
                        None if pd.isna(model_age_label) else str(model_age_label)
                    ),
                }
            )
        yield records


# ---------------------------------------------------------------------------
# 기존 local/Oracle 조회 호환 계층
# ---------------------------------------------------------------------------

from pathlib import Path
from typing import Any

import pandas as pd


MODEL_INPUT_COLUMNS = [
    "GRID_CD",
    "시군구",
    "행정동",
    "sex_code",
    "성별",
    "aligned_age_order",
    "aligned_age_group",
    "model_age_code",
    "model_age_label",
    "preference_model_applicable",
    "alignment_status",
    "alignment_note",
    "source_age_groups",
    "source_age_group_count",
    "target_population_est",
]


def _validate_model_input(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(MODEL_INPUT_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"15세 이상 격자 대상자 입력 열이 없습니다: {missing}")
    result = frame[MODEL_INPUT_COLUMNS].copy()
    for column in (
        "sex_code",
        "aligned_age_order",
        "model_age_code",
        "source_age_group_count",
        "target_population_est",
    ):
        result[column] = pd.to_numeric(result[column], errors="raise").astype("int64")
    if result["preference_model_applicable"].dtype != bool:
        model_applicable = (
            result["preference_model_applicable"]
            .astype("string")
            .str.strip()
            .str.lower()
            .map({"true": True, "1": True, "y": True, "false": False, "0": False, "n": False})
        )
        if model_applicable.isna().any():
            raise ValueError("preference_model_applicable 값이 True/False가 아닙니다.")
        result["preference_model_applicable"] = model_applicable.astype(bool)
    if len(result) != 847_392 or result["GRID_CD"].nunique() != 60_528:
        raise ValueError(
            "15세 이상 격자 대상자 행·격자 수가 다릅니다: "
            f"rows={len(result):,}, grids={result['GRID_CD'].nunique():,}"
        )
    if result.duplicated(["GRID_CD", "sex_code", "model_age_code"]).any():
        raise ValueError("15세 이상 격자 대상자 입력 키가 중복됩니다.")
    if (result["target_population_est"] < 0).any():
        raise ValueError("15세 이상 격자 대상자 수에 음수가 있습니다.")
    if int(result["target_population_est"].sum()) != 545_692:
        raise ValueError("15세 이상 격자 대상자 총량이 545,692명과 다릅니다.")
    return result.reset_index(drop=True)


def load_grid_model_input_from_local(project_root: str | Path) -> pd.DataFrame:
    """기존 로컬 CSV에서 15세 이상 격자 대상자 모델 입력을 읽는다."""

    path = (
        Path(project_root)
        / "data/processed/preference_analysis/population/"
        "grid_sex_age_target_population_model_input_2024.csv"
    )
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"GRID_CD": "string"})
    return _validate_model_input(frame)


def summarize_grid_model_input_from_oracle(connection: Any) -> dict[str, int]:
    """Oracle 안에서 모델 입력 품질을 집계하고 요약값 한 행만 반환한다.

    실제 분석용 ``load_grid_model_input_from_oracle``과 달리 84만여 행을
    클라이언트로 내려받지 않는다. 이 함수는 실행 전 준비 상태를 빠르게
    확인하는 용도다.
    """

    query = """
        SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT grid_cd) AS grid_count,
            COUNT(DISTINCT sex_code) AS sex_count,
            COUNT(DISTINCT model_age_code) AS age_count,
            SUM(target_population_est) AS target_population_15plus,
            COUNT(*) - COUNT(DISTINCT (
                grid_cd || CHR(31) || TO_CHAR(sex_code)
                || CHR(31) || TO_CHAR(model_age_code)
            )) AS duplicate_keys,
            SUM(CASE WHEN target_population_est < 0 THEN 1 ELSE 0 END)
                AS negative_population_rows,
            SUM(CASE
                WHEN grid_cd IS NULL
                  OR district_name IS NULL
                  OR dong_name IS NULL
                  OR sex_code IS NULL
                  OR model_age_code IS NULL
                  OR target_population_est IS NULL
                THEN 1 ELSE 0
            END) AS missing_required_rows,
            COUNT(DISTINCT reference_year) AS reference_year_count,
            MIN(reference_year) AS reference_year_min,
            MAX(reference_year) AS reference_year_max,
            SUM(CASE WHEN proxy_flag <> 'Y' THEN 1 ELSE 0 END)
                AS non_proxy_rows,
            SUM(CASE WHEN overlap_adjusted <> 'N' THEN 1 ELSE 0 END)
                AS overlap_adjusted_rows
        FROM VW_GRID_TARGET_MODEL_INPUT
    """
    with connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    if row is None or row[0] == 0:
        raise ValueError(
            "Oracle에 성공한 15세 이상 격자 대상자 ETL 결과가 없습니다."
        )

    columns = (
        "rows",
        "grid_count",
        "sex_count",
        "age_count",
        "target_population_15plus",
        "duplicate_keys",
        "negative_population_rows",
        "missing_required_rows",
        "reference_year_count",
        "reference_year_min",
        "reference_year_max",
        "non_proxy_rows",
        "overlap_adjusted_rows",
    )
    return {column: int(value) for column, value in zip(columns, row, strict=True)}


def load_grid_model_input_from_oracle(connection: Any) -> pd.DataFrame:
    """최신 성공 ETL의 15세 이상 2×7 셀을 기존 15열 형태로 반환한다."""

    query = """
        SELECT
            grid_cd, district_name, dong_name, sex_code, sex_label,
            aligned_age_order, aligned_age_group, model_age_code,
            model_age_label, model_applicable, alignment_status,
            alignment_note, source_age_groups, source_age_group_count,
            target_population_est
        FROM VW_GRID_TARGET_MODEL_INPUT
        ORDER BY grid_cd, sex_code, aligned_age_order
    """
    with connection.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    if not rows:
        raise ValueError(
            "Oracle에 성공한 15세 이상 격자 대상자 ETL 결과가 없습니다."
        )

    frame = pd.DataFrame(
        rows,
        columns=[
            "GRID_CD",
            "시군구",
            "행정동",
            "sex_code",
            "성별",
            "aligned_age_order",
            "aligned_age_group",
            "model_age_code",
            "model_age_label",
            "preference_model_applicable",
            "alignment_status",
            "alignment_note",
            "source_age_groups",
            "source_age_group_count",
            "target_population_est",
        ],
    )
    frame["preference_model_applicable"] = frame[
        "preference_model_applicable"
    ].eq("Y")
    return _validate_model_input(frame)


def load_grid_model_input(
    *,
    backend: str,
    project_root: str | Path,
    oracle_connection: Any | None = None,
) -> pd.DataFrame:
    """선택한 backend에서 같은 15열 격자 대상자 입력을 반환한다."""

    normalized = backend.strip().lower()
    if normalized == "local":
        return load_grid_model_input_from_local(project_root)
    if normalized == "oracle":
        if oracle_connection is None:
            raise ValueError("oracle backend에는 oracle_connection이 필요합니다.")
        return load_grid_model_input_from_oracle(oracle_connection)
    raise ValueError("backend는 local 또는 oracle이어야 합니다.")
