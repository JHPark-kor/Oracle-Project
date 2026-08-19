"""Portable inference and accessibility-integration helpers.

The fitted survey model uses the derived ``sex_age_code`` interaction.  This
module exposes a deployment pipeline that accepts only the documented raw
columns, validates their code ranges, and derives that interaction before the
stored preprocessing/model pipeline runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import Pipeline

from .mapping import (
    OTHER_CATEGORY,
    POLICY_EXCLUDED_PREFERENCE_CATEGORIES,
    PREFERENCE_OUTPUT_CATEGORIES,
    UNMODELED_PREFERENCE_CATEGORIES,
)
from .modeling import AGE_LABELS, MODEL_FEATURES, SEX_LABELS


RAW_PREDICTION_COLUMNS: tuple[str, ...] = (
    "sex_code",
    "age_code",
    "survey_year",
)
SUPPORTED_SURVEY_YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
DEPLOYMENT_INPUT_STEP = "input_adapter"
DEPLOYMENT_MODEL_STEP = "preference_model"


def prepare_prediction_input(data: pd.DataFrame) -> pd.DataFrame:
    """Validate raw prediction columns and derive the model interaction code.

    Extra columns such as ``GRID_CD`` are allowed but are not passed into the
    statistical model.  This lets callers retain identifiers in their source
    frame while keeping the model contract limited to three raw features.
    """

    if not isinstance(data, pd.DataFrame):
        raise TypeError("선호확률 입력은 pandas.DataFrame이어야 합니다.")

    missing = sorted(set(RAW_PREDICTION_COLUMNS) - set(data.columns))
    if missing:
        raise ValueError(f"선호확률 입력 열이 누락되었습니다: {missing}")

    frame = data.loc[:, RAW_PREDICTION_COLUMNS].copy()
    for column in RAW_PREDICTION_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if frame.isna().any(axis=None):
        invalid = frame.columns[frame.isna().any()].tolist()
        raise ValueError(f"입력 코드에 결측 또는 숫자 변환 실패가 있습니다: {invalid}")
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("입력 코드는 모두 유한한 숫자여야 합니다.")

    for column in RAW_PREDICTION_COLUMNS:
        values = frame[column].to_numpy(dtype=float)
        if not np.allclose(values, np.round(values), atol=0.0):
            raise ValueError(f"{column}은 정수 코드여야 합니다.")
        frame[column] = np.round(values).astype(np.int64)

    invalid_sex = sorted(set(frame["sex_code"]) - set(SEX_LABELS))
    invalid_age = sorted(set(frame["age_code"]) - set(AGE_LABELS))
    invalid_year = sorted(
        set(frame["survey_year"]) - set(SUPPORTED_SURVEY_YEARS)
    )
    if invalid_sex:
        raise ValueError(f"정의되지 않은 성별 코드가 있습니다: {invalid_sex}")
    if invalid_age:
        raise ValueError(f"정의되지 않은 연령 코드가 있습니다: {invalid_age}")
    if invalid_year:
        raise ValueError(
            "지원하지 않는 조사연도입니다: "
            f"{invalid_year}; allowed={list(SUPPORTED_SURVEY_YEARS)}"
        )

    frame["sex_age_code"] = (
        frame["sex_code"].astype("string")
        + "_"
        + frame["age_code"].astype("string")
    )
    return frame.loc[:, MODEL_FEATURES]


class PreferenceInputTransformer(TransformerMixin, BaseEstimator):
    """Sklearn-compatible adapter for the public three-column input contract."""

    def fit(self, X: pd.DataFrame, y: Any = None) -> "PreferenceInputTransformer":
        prepare_prediction_input(X)
        self.feature_names_in_ = np.asarray(RAW_PREDICTION_COLUMNS, dtype=object)
        self.n_features_in_ = len(RAW_PREDICTION_COLUMNS)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return prepare_prediction_input(X)

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        return np.asarray(MODEL_FEATURES, dtype=object)


def _fitted_preference_model(model: Pipeline) -> Pipeline:
    if not isinstance(model, Pipeline):
        raise TypeError("선호모델 객체는 sklearn.pipeline.Pipeline이어야 합니다.")
    if DEPLOYMENT_MODEL_STEP in model.named_steps:
        nested = model.named_steps[DEPLOYMENT_MODEL_STEP]
        if not isinstance(nested, Pipeline):
            raise TypeError("배포 Pipeline 내부 선호모델이 Pipeline이 아닙니다.")
        return nested
    return model


def predict_proba_class_order(model: Pipeline) -> tuple[str, ...]:
    """Return the exact column order used by ``predict_proba``."""

    fitted = _fitted_preference_model(model)
    classifier = fitted.named_steps.get("classifier")
    if classifier is None or not hasattr(classifier, "classes_"):
        raise ValueError("학습된 classifier와 classes_를 찾을 수 없습니다.")
    return tuple(str(value) for value in classifier.classes_)


def build_deployment_pipeline(fitted_model: Pipeline) -> Pipeline:
    """Wrap the fitted preprocessing/model Pipeline with raw-input validation."""

    predict_proba_class_order(fitted_model)
    return Pipeline(
        steps=[
            (DEPLOYMENT_INPUT_STEP, PreferenceInputTransformer()),
            (DEPLOYMENT_MODEL_STEP, fitted_model),
        ]
    )


def load_preference_pipeline(path: str | Path) -> Pipeline:
    """Load and validate a teammate-facing deployment Pipeline."""

    model = joblib.load(Path(path))
    if not isinstance(model, Pipeline):
        raise TypeError("Joblib 파일에 sklearn Pipeline이 없습니다.")
    predict_proba_class_order(model)
    return model


def predict_probability_frame(
    model: Pipeline,
    data: pd.DataFrame,
    *,
    probability_prefix: str = "probability__",
) -> pd.DataFrame:
    """Return labeled probability columns while preserving caller identifiers."""

    classes = predict_proba_class_order(model)
    probabilities = np.asarray(model.predict_proba(data), dtype=float)
    if probabilities.shape != (len(data), len(classes)):
        raise ValueError(
            "predict_proba 결과 크기가 클래스 계약과 다릅니다: "
            f"actual={probabilities.shape}, expected={(len(data), len(classes))}"
        )
    if not np.isfinite(probabilities).all():
        raise ValueError("predict_proba 결과에 NaN 또는 무한대가 있습니다.")
    if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("행별 predict_proba 확률합이 1이 아닙니다.")

    output = data.reset_index(drop=True).copy()
    for index, category in enumerate(classes):
        output[f"{probability_prefix}{category}"] = probabilities[:, index]
    return output


def build_accessibility_category_contract() -> pd.DataFrame:
    """Describe the explicit category overlap with the latest H3SFCA output."""

    accessibility_categories = [
        "도서",
        "문화체험",
        "음악",
        "영상",
        "체육시설",
        "체육용품",
        "공연",
        "관광지",
        "미술",
        "스포츠관람",
    ]
    rows: list[dict[str, Any]] = []
    for category in accessibility_categories:
        if category in PREFERENCE_OUTPUT_CATEGORIES:
            status = "supported"
            preference_category: Any = category
            merge_allowed = True
            note = "선호 절대확률·잠재수요와 중분류명이 동일하여 결합 가능"
        elif category in POLICY_EXCLUDED_PREFERENCE_CATEGORIES:
            status = "policy_excluded"
            preference_category = pd.NA
            merge_allowed = False
            note = "음악 청취 활동은 지역 가맹점 접근성 수요를 대표하지 않아 미산출"
        elif category in UNMODELED_PREFERENCE_CATEGORIES:
            status = "unmodeled"
            preference_category = pd.NA
            merge_allowed = False
            note = "체육용품 구매선호를 설문 활동 하나로 대표할 수 없어 미산출"
        else:
            status = "unsupported"
            preference_category = pd.NA
            merge_allowed = False
            note = "선호모델 계약에 없는 접근성 중분류"
        rows.append(
            {
                "accessibility_middle_category": category,
                "preference_middle_category": preference_category,
                "preference_status": status,
                "merge_allowed": merge_allowed,
                "missing_value_policy": (
                    "not_applicable" if merge_allowed else "NA_not_zero"
                ),
                "note": note,
            }
        )
    return pd.DataFrame(rows)


def build_h3sfca_demand_table(grid_preference: pd.DataFrame) -> pd.DataFrame:
    """Convert grid preference output to the demand schema used inside H3SFCA.

    The returned ``수요인구수`` must replace the current total target population
    before facility demand and H3SFCA are recalculated.  It is not a post-hoc
    weight for an already calculated H3SFCA score.
    """

    required = {"GRID_CD", "middle_category", "potential_demand_absolute"}
    missing = sorted(required - set(grid_preference.columns))
    if missing:
        raise ValueError(f"격자 선호 결과 열이 누락되었습니다: {missing}")

    demand = grid_preference.loc[
        grid_preference["middle_category"].isin(PREFERENCE_OUTPUT_CATEGORIES),
        ["GRID_CD", "middle_category", "potential_demand_absolute"],
    ].copy()
    if demand[["GRID_CD", "middle_category"]].duplicated().any():
        raise ValueError("격자 선호 결과의 (GRID_CD, middle_category)가 중복됩니다.")
    demand["potential_demand_absolute"] = pd.to_numeric(
        demand["potential_demand_absolute"], errors="coerce"
    )
    if demand["potential_demand_absolute"].isna().any():
        raise ValueError("격자 절대 잠재수요에 결측 또는 숫자 변환 실패가 있습니다.")
    values = demand["potential_demand_absolute"].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("격자 절대 잠재수요는 유한한 0 이상 값이어야 합니다.")

    return (
        demand.rename(
            columns={
                "middle_category": "중분류",
                "potential_demand_absolute": "수요인구수",
            }
        )
        .sort_values(["GRID_CD", "중분류"], ignore_index=True)
    )


def merge_preference_with_h3sfca(
    accessibility: pd.DataFrame,
    grid_preference: pd.DataFrame,
) -> pd.DataFrame:
    """Attach preference metrics to H3SFCA rows without fabricating zeroes."""

    access_required = {"접근수단", "GRID_CD", "중분류"}
    preference_required = {
        "GRID_CD",
        "middle_category",
        "preference_probability_absolute",
        "potential_demand_absolute",
    }
    missing_access = sorted(access_required - set(accessibility.columns))
    missing_preference = sorted(preference_required - set(grid_preference.columns))
    if missing_access:
        raise ValueError(f"H3SFCA 결과 열이 누락되었습니다: {missing_access}")
    if missing_preference:
        raise ValueError(f"격자 선호 결과 열이 누락되었습니다: {missing_preference}")
    if accessibility[list(access_required)].duplicated().any():
        raise ValueError("H3SFCA 결과의 (접근수단, GRID_CD, 중분류)가 중복됩니다.")
    if grid_preference[["GRID_CD", "middle_category"]].duplicated().any():
        raise ValueError("격자 선호 결과의 (GRID_CD, middle_category)가 중복됩니다.")

    contract = build_accessibility_category_contract()
    merged = accessibility.merge(
        contract,
        left_on="중분류",
        right_on="accessibility_middle_category",
        how="left",
        validate="many_to_one",
    )
    if merged["preference_status"].isna().any():
        unknown = sorted(merged.loc[merged["preference_status"].isna(), "중분류"].unique())
        raise ValueError(f"계약에 없는 접근성 중분류가 있습니다: {unknown}")

    preference_columns = [
        "GRID_CD",
        "middle_category",
        "preference_probability_absolute",
        "potential_demand_absolute",
    ]
    for optional in (
        "preference_share_conditional_mnc",
        "other_probability_absolute",
    ):
        if optional in grid_preference.columns:
            preference_columns.append(optional)
    merged = merged.merge(
        grid_preference[preference_columns],
        left_on=["GRID_CD", "preference_middle_category"],
        right_on=["GRID_CD", "middle_category"],
        how="left",
        validate="many_to_one",
    )

    supported = merged["merge_allowed"].fillna(False)
    if merged.loc[supported, "potential_demand_absolute"].isna().any():
        count = int(merged.loc[supported, "potential_demand_absolute"].isna().sum())
        raise ValueError(f"결합 가능한 H3SFCA 행 중 선호 결과가 없는 행이 있습니다: {count:,}행")
    if merged.loc[~supported, "potential_demand_absolute"].notna().any():
        raise ValueError("미산출 접근성 중분류에 선호 잠재수요가 잘못 결합되었습니다.")
    return merged
