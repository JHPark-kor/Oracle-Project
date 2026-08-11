"""Descriptive external-validity checks against 2024 MNC card usage.

Predicted satisfaction-based preference and observed card transactions measure
different constructs.  Results from this module are therefore concordance
diagnostics, never model accuracy or causal effects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .mapping import PREFERENCE_OUTPUT_CATEGORIES
from .spatial_demand import (
    ABSOLUTE_PROBABILITY_COLUMN,
    CONDITIONAL_SHARE_COLUMN,
    POTENTIAL_DEMAND_COLUMN,
    TARGET_POPULATION_COLUMN,
)


CARD_VALIDATION_CROSSWALK: dict[str, tuple[str, ...]] = {
    "도서": ("도서",),
    "음악": ("음악",),
    "영상": ("영화", "TV"),
    "공연": ("공연",),
    "미술": ("전시", "사진관"),
    "문화체험": ("공예", "문화체험", "직업체험", "문화일반"),
    "관광지": (
        "관광명소",
        "휴양림캠핑장",
        "동식물원",
        "온천",
        "체험관광",
        "테마파크",
    ),
    "스포츠관람": ("스포츠관람",),
    "체육시설": ("체육시설",),
}

CARD_VALIDATION_CROSSWALK_VARIANTS: dict[
    str, dict[str, tuple[str, ...]]
] = {
    "primary_semantic_v1": CARD_VALIDATION_CROSSWALK,
    "legacy_eda_craft_as_art_v1": {
        **CARD_VALIDATION_CROSSWALK,
        "미술": ("전시", "공예", "사진관"),
        "문화체험": ("문화체험", "직업체험", "문화일반"),
    },
    "conservative_exclude_craft_general_v1": {
        **CARD_VALIDATION_CROSSWALK,
        "문화체험": ("문화체험", "직업체험"),
    },
}

CARD_GEOGRAPHY_BASIS = "unverified"
CARD_GEOGRAPHY_INTERPRETATION_LIMIT = (
    "이용자 거주지·이용 가맹점 소재지·온라인/역외 이용 구분 미확인"
)
ARTS_POPULATION_SCOPE = "전국 조사표본"

CARD_COMPARABILITY = {
    "도서": ("보통", "독서 만족활동과 카드 도서구매는 동일 개념이 아님"),
    "음악": ("보통 이하", "음악 청취·스트리밍과 유료 음악 가맹점 이용 차이"),
    "영상": ("보통 이상", "설문 영상은 영화 외 TV·OTT·스포츠매체도 포함"),
    "공연": ("높음", "가장 직접적으로 대응되는 분야"),
    "미술": ("보통", "설문은 박물관·개인 사진활동도 포함"),
    "문화체험": ("보통 이하", "문화일반과 공예의 범위가 넓음"),
    "관광지": ("보통·부분", "설문은 등산·축제·소풍·목욕 등도 포함"),
    "스포츠관람": ("높음", "개념 대응은 높지만 카드 거래비중이 작음"),
    "체육시설": ("보통", "설문은 비시설 야외운동도 포함"),
}

EXCLUDED_CARD_CATEGORIES = (
    "철도",
    "시외고속버스",
    "국내항공",
    "여객선",
    "렌터카",
    "여행사",
    "숙박",
    "체육용품",
)

ARTS_ATTENDANCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "공연": (
        "문화예술행사 직접관람 횟수_서양음악",
        "문화예술행사 직접관람 횟수_전통예술",
        "문화예술행사 직접관람 횟수_연극",
        "문화예술행사 직접관람 횟수_뮤지컬",
        "문화예술행사 직접관람 횟수_무용",
        "문화예술행사 직접관람 횟수_대중음악/연예",
    ),
    "미술": ("문화예술행사 직접관람 횟수_미술전시회",),
    "영상": ("문화예술행사 직접관람 횟수_영화",),
}


def build_validation_crosswalk_table(
    crosswalk: dict[str, tuple[str, ...]] = CARD_VALIDATION_CROSSWALK,
    *,
    crosswalk_version: str = "primary_semantic_v1",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for category in PREFERENCE_OUTPUT_CATEGORIES:
        comparability, caveat = CARD_COMPARABILITY[category]
        rows.append(
            {
                "model_middle_category": category,
                "card_usage_categories": " + ".join(
                    crosswalk[category]
                ),
                "comparability": comparability,
                "caveat": caveat,
                "crosswalk_version": crosswalk_version,
            }
        )
    return pd.DataFrame(rows)


def _spearman(left: pd.Series, right: pd.Series) -> float:
    valid = left.notna() & right.notna()
    if int(valid.sum()) < 2:
        return float("nan")
    left_valid = left.loc[valid]
    right_valid = right.loc[valid]
    if left_valid.nunique() < 2 or right_valid.nunique() < 2:
        return float("nan")
    return float(left_valid.rank().corr(right_valid.rank()))


def _validate_inputs(
    gu_demand: pd.DataFrame,
    usage: pd.DataFrame,
    year: int,
    crosswalk: dict[str, tuple[str, ...]],
) -> None:
    required_gu = {
        "시군구",
        "middle_category",
        TARGET_POPULATION_COLUMN,
        ABSOLUTE_PROBABILITY_COLUMN,
        POTENTIAL_DEMAND_COLUMN,
        CONDITIONAL_SHARE_COLUMN,
    }
    missing_gu = sorted(required_gu - set(gu_demand.columns))
    if missing_gu:
        raise ValueError(f"자치구 잠재수요에 필요한 열이 없습니다: {missing_gu}")
    actual_categories = set(gu_demand["middle_category"])
    if actual_categories != set(PREFERENCE_OUTPUT_CATEGORIES):
        raise ValueError(
            "자치구 잠재수요는 정책 9개 분야를 모두 포함해야 합니다: "
            f"actual={sorted(actual_categories)}"
        )
    if gu_demand.duplicated(["시군구", "middle_category"]).any():
        raise ValueError("자치구×분야 잠재수요 키가 고유하지 않습니다.")
    if not {"year", "district", "transactions", "used_amount_won"}.issubset(
        usage.columns
    ):
        raise ValueError("문화누리 이용실적 기본 열이 없습니다.")
    year_rows = usage.loc[usage["year"].eq(year)]
    if len(year_rows) != 25 or year_rows["district"].nunique() != 25:
        raise ValueError(f"{year}년 이용실적은 서울 25개 자치구여야 합니다.")
    if set(year_rows["district"]) != set(gu_demand["시군구"]):
        raise ValueError("이용실적과 잠재수요의 자치구 집합이 일치하지 않습니다.")
    required_card_columns = {
        f"{prefix}_{category}"
        for prefix in ("count", "amount")
        for categories in crosswalk.values()
        for category in categories
    }
    missing_card = sorted(required_card_columns - set(usage.columns))
    if missing_card:
        raise ValueError(f"이용실적 중분류 열이 없습니다: {missing_card}")


def build_card_external_validation(
    gu_demand: pd.DataFrame,
    usage: pd.DataFrame,
    *,
    year: int = 2024,
    crosswalk: dict[str, tuple[str, ...]] = CARD_VALIDATION_CROSSWALK,
    crosswalk_version: str = "primary_semantic_v1",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compare predicted composition with mapped card usage descriptively."""

    if set(crosswalk) != set(PREFERENCE_OUTPUT_CATEGORIES):
        raise ValueError("카드 외부검증 crosswalk는 정책 9개 분야를 모두 포함해야 합니다.")
    _validate_inputs(gu_demand, usage, year, crosswalk)
    year_usage = usage.loc[usage["year"].eq(year)].copy()
    rows: list[dict[str, object]] = []
    for usage_row in year_usage.itertuples(index=False):
        row_values = usage_row._asdict()
        for category in PREFERENCE_OUTPUT_CATEGORIES:
            card_categories = crosswalk[category]
            rows.append(
                {
                    "reference_year": year,
                    "시군구": row_values["district"],
                    "middle_category": category,
                    "card_transaction_count": float(
                        sum(row_values[f"count_{name}"] for name in card_categories)
                    ),
                    "card_amount_won": float(
                        sum(row_values[f"amount_{name}"] for name in card_categories)
                    ),
                    "card_all_transactions": float(row_values["transactions"]),
                    "card_all_amount_won": float(row_values["used_amount_won"]),
                }
            )
    card = pd.DataFrame(rows)
    card["card_mapped9_transactions"] = card.groupby("시군구", observed=False)[
        "card_transaction_count"
    ].transform("sum")
    card["card_mapped9_amount_won"] = card.groupby("시군구", observed=False)[
        "card_amount_won"
    ].transform("sum")
    card["card_transaction_share_mapped9"] = (
        card["card_transaction_count"] / card["card_mapped9_transactions"]
    )
    card["card_amount_share_mapped9"] = (
        card["card_amount_won"] / card["card_mapped9_amount_won"]
    )
    card["mapped9_transaction_coverage"] = (
        card["card_mapped9_transactions"] / card["card_all_transactions"]
    )
    card["mapped9_amount_coverage"] = (
        card["card_mapped9_amount_won"] / card["card_all_amount_won"]
    )

    predicted = gu_demand[
        [
            "시군구",
            "middle_category",
            TARGET_POPULATION_COLUMN,
            ABSOLUTE_PROBABILITY_COLUMN,
            POTENTIAL_DEMAND_COLUMN,
            CONDITIONAL_SHARE_COLUMN,
        ]
    ].copy()
    comparison = predicted.merge(
        card,
        on=["시군구", "middle_category"],
        how="inner",
        validate="one_to_one",
    )
    comparison["transaction_share_difference"] = (
        comparison[CONDITIONAL_SHARE_COLUMN]
        - comparison["card_transaction_share_mapped9"]
    )
    comparison["amount_share_difference"] = (
        comparison[CONDITIONAL_SHARE_COLUMN]
        - comparison["card_amount_share_mapped9"]
    )

    district_rows: list[dict[str, object]] = []
    for district, group in comparison.groupby("시군구", observed=False):
        transaction_tv = 0.5 * float(
            np.abs(
                group[CONDITIONAL_SHARE_COLUMN]
                - group["card_transaction_share_mapped9"]
            ).sum()
        )
        amount_tv = 0.5 * float(
            np.abs(
                group[CONDITIONAL_SHARE_COLUMN]
                - group["card_amount_share_mapped9"]
            ).sum()
        )
        district_rows.append(
            {
                "reference_year": year,
                "시군구": district,
                "transaction_spearman_rho": _spearman(
                    group[CONDITIONAL_SHARE_COLUMN],
                    group["card_transaction_share_mapped9"],
                ),
                "amount_spearman_rho": _spearman(
                    group[CONDITIONAL_SHARE_COLUMN],
                    group["card_amount_share_mapped9"],
                ),
                "transaction_distribution_match_score": 100.0
                * (1.0 - transaction_tv),
                "amount_distribution_match_score": 100.0 * (1.0 - amount_tv),
                "mapped9_transaction_coverage": float(
                    group["mapped9_transaction_coverage"].iloc[0]
                ),
                "mapped9_amount_coverage": float(
                    group["mapped9_amount_coverage"].iloc[0]
                ),
            }
        )
    district_summary = pd.DataFrame(district_rows)

    category_rows: list[dict[str, object]] = []
    for category, group in comparison.groupby("middle_category", observed=False):
        category_rows.append(
            {
                "reference_year": year,
                "middle_category": category,
                "district_count": int(group["시군구"].nunique()),
                "absolute_probability_vs_transaction_share_spearman": _spearman(
                    group[ABSOLUTE_PROBABILITY_COLUMN],
                    group["card_transaction_share_mapped9"],
                ),
                "absolute_probability_vs_amount_share_spearman": _spearman(
                    group[ABSOLUTE_PROBABILITY_COLUMN],
                    group["card_amount_share_mapped9"],
                ),
                "potential_demand_vs_transaction_count_spearman_size_sensitive": _spearman(
                    group[POTENTIAL_DEMAND_COLUMN],
                    group["card_transaction_count"],
                ),
                "interpretation": (
                    "선호와 실제 이용의 방향성 점검이며 모델 정확도·오차율이 아님"
                ),
            }
        )
    category_summary = pd.DataFrame(category_rows)

    predicted_seoul = comparison.groupby("middle_category", observed=False)[
        POTENTIAL_DEMAND_COLUMN
    ].sum()
    predicted_seoul = predicted_seoul / predicted_seoul.sum()
    transaction_seoul = comparison.groupby("middle_category", observed=False)[
        "card_transaction_count"
    ].sum()
    transaction_seoul = transaction_seoul / transaction_seoul.sum()
    amount_seoul = comparison.groupby("middle_category", observed=False)[
        "card_amount_won"
    ].sum()
    amount_seoul = amount_seoul / amount_seoul.sum()
    transaction_tv = 0.5 * float(np.abs(predicted_seoul - transaction_seoul).sum())
    amount_tv = 0.5 * float(np.abs(predicted_seoul - amount_seoul).sum())
    summary = pd.DataFrame(
        [
            {
                "reference_year": year,
                "metric": "mapped9_transaction_coverage",
                "value": float(
                    card.drop_duplicates("시군구")["card_mapped9_transactions"].sum()
                    / card.drop_duplicates("시군구")["card_all_transactions"].sum()
                ),
                "interpretation": "전체 카드 이용건수 중 설정된 crosswalk로 매핑된 정책 9개 분야 비중",
            },
            {
                "reference_year": year,
                "metric": "mapped9_amount_coverage",
                "value": float(
                    card.drop_duplicates("시군구")["card_mapped9_amount_won"].sum()
                    / card.drop_duplicates("시군구")["card_all_amount_won"].sum()
                ),
                "interpretation": "전체 카드 이용금액 중 설정된 crosswalk로 매핑된 정책 9개 분야 비중",
            },
            {
                "reference_year": year,
                "metric": "seoul_transaction_spearman_rho_9categories",
                "value": _spearman(predicted_seoul, transaction_seoul),
                "interpretation": "서울 전체 9개 분야 순위 일치 방향성",
            },
            {
                "reference_year": year,
                "metric": "seoul_amount_spearman_rho_9categories",
                "value": _spearman(predicted_seoul, amount_seoul),
                "interpretation": "서울 전체 9개 분야 금액 순위 일치 방향성",
            },
            {
                "reference_year": year,
                "metric": "seoul_transaction_distribution_match_score",
                "value": 100.0 * (1.0 - transaction_tv),
                "interpretation": "예측 조건부 구성과 카드 거래 구성의 기술적 분포 일치도; 모델 성능점수가 아님",
            },
            {
                "reference_year": year,
                "metric": "seoul_amount_distribution_match_score",
                "value": 100.0 * (1.0 - amount_tv),
                "interpretation": "예측 조건부 구성과 카드 금액 구성의 기술적 분포 일치도; 모델 성능점수가 아님",
            },
        ]
    )
    for frame in (comparison, district_summary, category_summary, summary):
        frame.insert(1, "crosswalk_version", crosswalk_version)
        frame["card_geography_basis"] = CARD_GEOGRAPHY_BASIS
        frame["card_geography_interpretation_limit"] = (
            CARD_GEOGRAPHY_INTERPRETATION_LIMIT
        )
    district_summary["distribution_match_interpretation"] = (
        "기술적 분포 일치도이며 모델 Accuracy·오차율이 아님"
    )
    return comparison, district_summary, category_summary, summary


def build_card_crosswalk_sensitivity_summary(
    gu_demand: pd.DataFrame,
    usage: pd.DataFrame,
    *,
    year: int = 2024,
) -> pd.DataFrame:
    """Compare primary and plausible craft/general-category mappings."""

    summaries: list[pd.DataFrame] = []
    for version, crosswalk in CARD_VALIDATION_CROSSWALK_VARIANTS.items():
        _, _, _, summary = build_card_external_validation(
            gu_demand,
            usage,
            year=year,
            crosswalk=crosswalk,
            crosswalk_version=version,
        )
        summaries.append(summary)
    return pd.concat(summaries, ignore_index=True)


def build_arts_directional_validation(
    probability: pd.DataFrame,
    arts: pd.DataFrame,
    *,
    year: int = 2024,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Check national sex-age gradients for three partially comparable fields."""

    probability_column = (
        ABSOLUTE_PROBABILITY_COLUMN
        if ABSOLUTE_PROBABILITY_COLUMN in probability.columns
        else "preference_probability"
    )
    required_probability = {
        "sex_code",
        "age_code",
        "survey_year",
        "middle_category",
        probability_column,
    }
    missing_probability = sorted(required_probability - set(probability.columns))
    if missing_probability:
        raise ValueError(
            f"성별×연령 선호확률에 필요한 열이 없습니다: {missing_probability}"
        )
    required_arts = {
        "조사년도",
        "성별",
        "연령",
        "최종가중치",
        *(column for columns in ARTS_ATTENDANCE_COLUMNS.values() for column in columns),
    }
    missing_arts = sorted(required_arts - set(arts.columns))
    if missing_arts:
        raise ValueError(f"국민문화예술활동조사에 필요한 열이 없습니다: {missing_arts}")
    arts_year = arts.loc[arts["조사년도"].eq(year)].copy()
    if arts_year.empty:
        raise ValueError(f"국민문화예술활동조사 {year}년 자료가 없습니다.")
    weight = pd.to_numeric(arts_year["최종가중치"], errors="coerce")
    if weight.isna().any() or (weight <= 0).any() or not np.isfinite(weight).all():
        raise ValueError("국민문화예술활동조사 가중치는 유한한 양수여야 합니다.")
    arts_year["survey_weight"] = weight

    rows: list[dict[str, object]] = []
    for category, columns in ARTS_ATTENDANCE_COLUMNS.items():
        numeric = arts_year.loc[:, list(columns)].apply(
            pd.to_numeric, errors="coerce"
        )
        if numeric.isna().any().any() or (numeric < 0).any().any():
            raise ValueError(f"{category} 직접관람 횟수에 결측 또는 음수가 있습니다.")
        attended = numeric.gt(0).any(axis=1).astype(float)
        working = arts_year[["성별", "연령", "survey_weight"]].copy()
        working["attended"] = attended
        for (sex_code, age_code), group in working.groupby(
            ["성별", "연령"], observed=False
        ):
            weighted_rate = float(
                np.average(group["attended"], weights=group["survey_weight"])
            )
            rows.append(
                {
                    "reference_year": year,
                    "population_scope": ARTS_POPULATION_SCOPE,
                    "sex_code": int(sex_code),
                    "age_code": int(age_code),
                    "middle_category": category,
                    "arts_weighted_attendance_rate": weighted_rate,
                    "arts_unweighted_respondents": int(len(group)),
                }
            )
    observed = pd.DataFrame(rows)
    predicted = probability.loc[
        probability["survey_year"].eq(year)
        & probability["middle_category"].isin(ARTS_ATTENDANCE_COLUMNS),
        ["sex_code", "age_code", "middle_category", probability_column],
    ].copy()
    predicted = predicted.rename(columns={probability_column: ABSOLUTE_PROBABILITY_COLUMN})
    comparison = observed.merge(
        predicted,
        on=["sex_code", "age_code", "middle_category"],
        how="left",
        validate="one_to_one",
    )
    if comparison[ABSOLUTE_PROBABILITY_COLUMN].isna().any() or len(comparison) != 42:
        raise ValueError("공연·미술·영상의 14개 성별×연령 셀 결합이 불완전합니다.")
    summary_rows: list[dict[str, object]] = []
    caveats = {
        "공연": "공연 직접관람 여부와 만족활동 선호의 성별×연령 방향성 비교",
        "미술": "미술전시 직접관람 여부와 만족활동 선호의 성별×연령 방향성 비교",
        "영상": "영화관람만 비교하므로 TV·OTT를 포함한 영상 분야와 부분 비교",
    }
    for category, group in comparison.groupby("middle_category", observed=False):
        summary_rows.append(
            {
                "reference_year": year,
                "population_scope": ARTS_POPULATION_SCOPE,
                "middle_category": category,
                "sex_age_cell_count": int(len(group)),
                "spearman_rho": _spearman(
                    group[ABSOLUTE_PROBABILITY_COLUMN],
                    group["arts_weighted_attendance_rate"],
                ),
                "interpretation": caveats[category],
            }
        )
    return comparison, pd.DataFrame(summary_rows)
