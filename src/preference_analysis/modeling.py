"""Survey-weighted multinomial preference modeling utilities.

The model target combines the first, second, and third most satisfying leisure
activities after middle-category mapping.  Future desired-activity fields are
never used.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, log_loss, top_k_accuracy_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .mapping import MODEL_CATEGORIES, OTHER_CATEGORY, PREFERENCE_OUTPUT_CATEGORIES


SOURCE_TARGET_COLUMNS: dict[int, str] = {
    1: "만족활동_1순위_중분류",
    2: "만족활동_2순위_중분류",
    3: "만족활동_3순위_중분류",
}
RANK_SCORES: dict[int, float] = {1: 3.0, 2: 2.0, 3: 1.0}
SOURCE_WEIGHT_COLUMN = "최종가중치"
SOURCE_FEATURE_COLUMNS: tuple[str, ...] = ("성별", "연령", "조사년도")

RESPONDENT_COLUMN = "respondent_id"
TARGET_COLUMN = "middle_category"
BASE_WEIGHT_COLUMN = "survey_weight_base"
WEIGHT_COLUMN = "survey_weight"
RANK_COLUMN = "satisfaction_rank"
RANK_SCORE_COLUMN = "rank_score"
RANK_WEIGHT_COLUMN = "rank_weight"
RANK_OCCURRENCE_COLUMN = "rank_occurrences"
ADDITIVE_FEATURE_MODE = "additive"
INTERACTION_FEATURE_MODE = "sex_age_interaction"
FEATURE_MODES: tuple[str, ...] = (
    ADDITIVE_FEATURE_MODE,
    INTERACTION_FEATURE_MODE,
)
CATEGORICAL_FEATURES_BY_MODE: dict[str, tuple[str, ...]] = {
    ADDITIVE_FEATURE_MODE: ("sex_code", "age_code"),
    INTERACTION_FEATURE_MODE: ("sex_age_code",),
}
NUMERIC_FEATURES: tuple[str, ...] = ("survey_year",)
MODEL_FEATURES: tuple[str, ...] = (
    "sex_code",
    "age_code",
    "sex_age_code",
    *NUMERIC_FEATURES,
)

SEX_LABELS = {1: "남성", 2: "여성"}
AGE_LABELS = {
    1: "15~19세",
    2: "20대",
    3: "30대",
    4: "40대",
    5: "50대",
    6: "60대",
    7: "70대 이상",
}


def prepare_model_frame(mapped_data: pd.DataFrame) -> pd.DataFrame:
    """Build a rank-weighted long model table from satisfaction ranks 1~3.

    Repeated middle categories within a respondent accumulate their 3:2:1 rank
    scores.  The category scores are then normalized within each respondent so
    the respondent's total effective weight equals the original survey weight.
    """

    required = {
        *SOURCE_TARGET_COLUMNS.values(),
        SOURCE_WEIGHT_COLUMN,
        *SOURCE_FEATURE_COLUMNS,
    }
    missing = sorted(required - set(mapped_data.columns))
    if missing:
        raise ValueError(f"모델 입력에 필요한 열이 없습니다: {missing}")

    source_columns = [
        *SOURCE_FEATURE_COLUMNS,
        *SOURCE_TARGET_COLUMNS.values(),
        SOURCE_WEIGHT_COLUMN,
    ]
    if "source_row_index" in mapped_data.columns:
        source_columns.insert(0, "source_row_index")
    source = mapped_data[source_columns].copy()
    if "source_row_index" not in source.columns:
        source.insert(0, "source_row_index", np.arange(len(source), dtype=np.int64))

    source = source.rename(
        columns={
            "source_row_index": RESPONDENT_COLUMN,
            "성별": "sex_code",
            "연령": "age_code",
            "조사년도": "survey_year",
            SOURCE_WEIGHT_COLUMN: BASE_WEIGHT_COLUMN,
        }
    )

    for column in ("sex_code", "age_code", "survey_year"):
        source[column] = pd.to_numeric(source[column], errors="coerce")
    source[RESPONDENT_COLUMN] = pd.to_numeric(
        source[RESPONDENT_COLUMN], errors="coerce"
    )
    source[BASE_WEIGHT_COLUMN] = pd.to_numeric(
        source[BASE_WEIGHT_COLUMN], errors="coerce"
    )

    invalid_required = source[
        [
            RESPONDENT_COLUMN,
            "sex_code",
            "age_code",
            "survey_year",
            BASE_WEIGHT_COLUMN,
        ]
    ].isna().any(axis=1)
    if invalid_required.any():
        raise ValueError(
            "만족활동 모델 입력의 응답자·특성·가중치에 결측 또는 숫자 변환 "
            "실패가 있습니다: "
            f"{int(invalid_required.sum()):,}행"
        )
    finite_columns = [
        RESPONDENT_COLUMN,
        "sex_code",
        "age_code",
        "survey_year",
        BASE_WEIGHT_COLUMN,
    ]
    if not np.isfinite(source[finite_columns].to_numpy(dtype=float)).all():
        raise ValueError("응답자·특성·가중치는 모두 유한한 숫자여야 합니다.")
    if source[RESPONDENT_COLUMN].duplicated().any():
        raise ValueError("응답자 식별자 source_row_index는 고유해야 합니다.")
    if (source[BASE_WEIGHT_COLUMN] <= 0).any():
        raise ValueError("최종가중치는 모두 0보다 커야 합니다.")

    source[RESPONDENT_COLUMN] = source[RESPONDENT_COLUMN].astype(np.int64)
    source["sex_code"] = source["sex_code"].astype(int)
    source["age_code"] = source["age_code"].astype(int)
    source["survey_year"] = source["survey_year"].astype(int)
    source["sex_age_code"] = (
        source["sex_code"].astype("string")
        + "_"
        + source["age_code"].astype("string")
    )

    invalid_sex = sorted(set(source["sex_code"]) - set(SEX_LABELS))
    invalid_age = sorted(set(source["age_code"]) - set(AGE_LABELS))
    if invalid_sex:
        raise ValueError(f"정의되지 않은 성별 코드가 있습니다: {invalid_sex}")
    if invalid_age:
        raise ValueError(f"정의되지 않은 연령 코드가 있습니다: {invalid_age}")

    id_columns = [
        RESPONDENT_COLUMN,
        *MODEL_FEATURES,
        BASE_WEIGHT_COLUMN,
    ]
    parts: list[pd.DataFrame] = []
    for rank, source_target in SOURCE_TARGET_COLUMNS.items():
        part = source[id_columns].copy()
        part[TARGET_COLUMN] = source[source_target].astype("string")
        part[RANK_COLUMN] = rank
        part[RANK_SCORE_COLUMN] = RANK_SCORES[rank]
        part = part.loc[part[TARGET_COLUMN].notna()].copy()
        parts.append(part)
    frame = pd.concat(parts, ignore_index=True)
    if frame.empty:
        raise ValueError("만족활동 1~3순위에 유효한 중분류가 없습니다.")
    missing_respondents = source[RESPONDENT_COLUMN].nunique() - frame[
        RESPONDENT_COLUMN
    ].nunique()
    if missing_respondents:
        raise ValueError(
            "만족활동 1~3순위가 모두 결측인 응답자가 있습니다: "
            f"{missing_respondents:,}명"
        )

    invalid_target = sorted(set(frame[TARGET_COLUMN]) - set(MODEL_CATEGORIES))
    if invalid_target:
        raise ValueError(f"정의되지 않은 중분류가 있습니다: {invalid_target}")

    frame[RANK_OCCURRENCE_COLUMN] = 1
    frame = (
        frame.groupby(
            [
                RESPONDENT_COLUMN,
                *MODEL_FEATURES,
                BASE_WEIGHT_COLUMN,
                TARGET_COLUMN,
            ],
            as_index=False,
            observed=False,
        )
        .agg(
            **{
                RANK_COLUMN: (RANK_COLUMN, "min"),
                RANK_SCORE_COLUMN: (RANK_SCORE_COLUMN, "sum"),
                RANK_OCCURRENCE_COLUMN: (RANK_OCCURRENCE_COLUMN, "sum"),
            }
        )
    )
    rank_score_sum = frame.groupby(RESPONDENT_COLUMN, observed=False)[
        RANK_SCORE_COLUMN
    ].transform("sum")
    frame[RANK_WEIGHT_COLUMN] = frame[RANK_SCORE_COLUMN] / rank_score_sum
    frame[WEIGHT_COLUMN] = frame[BASE_WEIGHT_COLUMN] * frame[RANK_WEIGHT_COLUMN]

    respondent_weight_sum = frame.groupby(RESPONDENT_COLUMN, observed=False)[
        WEIGHT_COLUMN
    ].sum()
    expected_weight = source.set_index(RESPONDENT_COLUMN)[BASE_WEIGHT_COLUMN].reindex(
        respondent_weight_sum.index
    )
    if not np.allclose(
        respondent_weight_sum.to_numpy(), expected_weight.to_numpy(), atol=1e-10
    ):
        raise ValueError("순위가중 후 응답자별 최종가중치 합이 보존되지 않았습니다.")
    if frame.duplicated([RESPONDENT_COLUMN, TARGET_COLUMN]).any():
        raise ValueError("응답자별 중분류 순위점수 합산에 실패했습니다.")
    return frame.sort_values(
        [RESPONDENT_COLUMN, RANK_COLUMN], ignore_index=True
    )


def normalized_training_weights(weights: pd.Series | np.ndarray) -> np.ndarray:
    """Preserve relative survey weights while fixing mean weight at one."""

    values = np.asarray(weights, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("학습 가중치는 비어 있지 않은 1차원 배열이어야 합니다.")
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("학습 가중치는 모두 유한한 양수여야 합니다.")
    return values / values.mean()


def build_multinomial_pipeline(
    c_value: float,
    feature_mode: str = ADDITIVE_FEATURE_MODE,
) -> Pipeline:
    """Create a multinomial logistic pipeline for directly mappable features."""

    if not np.isfinite(c_value) or c_value <= 0:
        raise ValueError("규제강도 C는 유한한 양수여야 합니다.")
    if feature_mode not in FEATURE_MODES:
        raise ValueError(
            f"지원하지 않는 피처 모드입니다: {feature_mode}; "
            f"allowed={list(FEATURE_MODES)}"
        )

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(drop="first", handle_unknown="ignore"),
                list(CATEGORICAL_FEATURES_BY_MODE[feature_mode]),
            ),
            ("numeric", StandardScaler(), list(NUMERIC_FEATURES)),
        ],
        remainder="drop",
    )
    classifier = LogisticRegression(
        C=float(c_value),
        solver="lbfgs",
        max_iter=2_000,
        tol=1e-8,
        random_state=42,
    )
    return Pipeline(
        steps=[("preprocessor", preprocessor), ("classifier", classifier)]
    )


def fit_multinomial_model(
    frame: pd.DataFrame,
    c_value: float,
    feature_mode: str = ADDITIVE_FEATURE_MODE,
) -> Pipeline:
    """Fit using normalized survey weights; class balancing is not applied."""

    model = build_multinomial_pipeline(c_value, feature_mode=feature_mode)
    weights = normalized_training_weights(frame[WEIGHT_COLUMN])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(
            frame[list(MODEL_FEATURES)],
            frame[TARGET_COLUMN],
            classifier__sample_weight=weights,
        )
    convergence_warnings = [
        item for item in caught if issubclass(item.category, ConvergenceWarning)
    ]
    if convergence_warnings:
        raise RuntimeError(
            "다항 로지스틱 회귀가 max_iter 안에 수렴하지 않았습니다: "
            f"{convergence_warnings[-1].message}"
        )
    return model


def validate_model_class_coverage(
    frame: pd.DataFrame,
    expected_classes: Iterable[str] = MODEL_CATEGORIES,
    *,
    context: str = "모델 입력",
) -> None:
    """Require the approved ten-class target set before production training."""

    expected = set(expected_classes)
    actual = set(frame[TARGET_COLUMN].dropna().astype(str))
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise ValueError(
            f"{context}의 중분류 클래스가 기대값과 다릅니다: "
            f"missing={missing}, unexpected={unexpected}"
        )


def weighted_class_prior(
    frame: pd.DataFrame,
    classes: Iterable[str],
) -> np.ndarray:
    """Return the weighted training class distribution as a naive baseline."""

    class_list = list(classes)
    weighted = (
        frame.groupby(TARGET_COLUMN, observed=False)[WEIGHT_COLUMN].sum().reindex(
            class_list, fill_value=0.0
        )
    )
    prior = weighted.to_numpy(dtype=float)
    if prior.sum() <= 0:
        raise ValueError("학습자료의 가중 클래스 합이 0입니다.")
    return prior / prior.sum()


def evaluate_probabilities(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    classes: Iterable[str],
) -> tuple[dict[str, float | int], pd.DataFrame]:
    """Evaluate individual classification and aggregate probability quality."""

    class_array = np.asarray(list(classes), dtype=object)
    probability_array = np.asarray(probabilities, dtype=float)
    if probability_array.shape != (len(frame), len(class_array)):
        raise ValueError(
            "예측확률 크기가 평가자료와 맞지 않습니다: "
            f"probabilities={probability_array.shape}, expected={(len(frame), len(class_array))}"
        )
    if not np.isfinite(probability_array).all():
        raise ValueError("예측확률에 결측 또는 무한대가 있습니다.")
    if (probability_array < 0).any() or (probability_array > 1).any():
        raise ValueError("예측확률은 0 이상 1 이하여야 합니다.")
    if not np.allclose(probability_array.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("각 응답자의 중분류 예측확률 합은 1이어야 합니다.")

    y_true = frame[TARGET_COLUMN].to_numpy(dtype=object)
    weights = frame[WEIGHT_COLUMN].to_numpy(dtype=float)
    predicted_index = probability_array.argmax(axis=1)
    y_pred = class_array[predicted_index]
    class_to_index = {category: index for index, category in enumerate(class_array)}
    true_index = np.fromiter(
        (class_to_index[value] for value in y_true), dtype=int, count=len(y_true)
    )
    one_hot = np.eye(len(class_array), dtype=float)[true_index]

    observed_weight = np.bincount(
        true_index, weights=weights, minlength=len(class_array)
    )
    observed_share = observed_weight / observed_weight.sum()
    predicted_share = np.average(probability_array, axis=0, weights=weights)
    absolute_difference = np.abs(predicted_share - observed_share)

    metrics: dict[str, float | int] = {
        "n_rows": int(len(frame)),
        "n_respondents": int(
            frame[RESPONDENT_COLUMN].nunique()
            if RESPONDENT_COLUMN in frame.columns
            else len(frame)
        ),
        "weight_sum": float(weights.sum()),
        "accuracy": float(np.average(y_pred == y_true, weights=weights)),
        "top3_accuracy": float(
            top_k_accuracy_score(
                y_true,
                probability_array,
                k=min(3, len(class_array)),
                labels=class_array,
                sample_weight=weights,
            )
        ),
        "log_loss": float(
            log_loss(
                y_true,
                probability_array,
                labels=class_array,
                sample_weight=weights,
            )
        ),
        "multiclass_brier": float(
            np.average(np.square(probability_array - one_hot).sum(axis=1), weights=weights)
        ),
        "macro_f1": float(
            f1_score(
                y_true,
                y_pred,
                labels=class_array,
                average="macro",
                sample_weight=weights,
                zero_division=0,
            )
        ),
        "distribution_match_score": float(
            100.0 * (1.0 - 0.5 * absolute_difference.sum())
        ),
        "mean_category_error_pp": float(100.0 * absolute_difference.mean()),
    }
    log_loss_score = float(100.0 * np.exp(-float(metrics["log_loss"])))
    # 0~100점으로 환산한 Log Loss의 단조변환이다. 정확도가 아니라
    # 모델이 실제 정답에 부여한 확률의 가중 기하평균을 뜻한다.
    metrics["log_loss_score"] = log_loss_score
    # 기존 산출물과 하위 호환을 유지한다.
    metrics["log_loss_probability_score"] = log_loss_score
    by_category = pd.DataFrame(
        {
            TARGET_COLUMN: class_array,
            "observed_rate": observed_share,
            "predicted_rate": predicted_share,
            "difference": predicted_share - observed_share,
            "absolute_difference_pp": 100.0 * absolute_difference,
            "observed_weighted_count": observed_weight,
        }
    )
    return metrics, by_category


def evaluate_model(
    model: Pipeline,
    frame: pd.DataFrame,
) -> tuple[dict[str, float | int], pd.DataFrame]:
    probabilities = model.predict_proba(frame[list(MODEL_FEATURES)])
    classes = model.named_steps["classifier"].classes_
    return evaluate_probabilities(frame, probabilities, classes)


def tune_regularization(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    c_values: Iterable[float],
    feature_mode: str = ADDITIVE_FEATURE_MODE,
) -> tuple[float, pd.DataFrame]:
    """Select C by validation log loss and retain overfitting diagnostics."""

    candidates = sorted({float(value) for value in c_values})
    if not candidates:
        raise ValueError("비교할 C 후보가 하나 이상 필요합니다.")
    if not np.isfinite(candidates).all() or any(value <= 0 for value in candidates):
        raise ValueError("모든 C 후보는 유한한 양수여야 합니다.")

    rows: list[dict[str, Any]] = []
    for c_value in candidates:
        model = fit_multinomial_model(train, c_value, feature_mode=feature_mode)
        train_metrics, _ = evaluate_model(model, train)
        validation_metrics, _ = evaluate_model(model, validation)
        rows.append(
            {
                "c_value": c_value,
                **validation_metrics,
                "train_log_loss": train_metrics["log_loss"],
                "train_multiclass_brier": train_metrics["multiclass_brier"],
                "train_top3_accuracy": train_metrics["top3_accuracy"],
                "log_loss_generalization_gap": (
                    validation_metrics["log_loss"] - train_metrics["log_loss"]
                ),
                "brier_generalization_gap": (
                    validation_metrics["multiclass_brier"]
                    - train_metrics["multiclass_brier"]
                ),
            }
        )

    tuning = pd.DataFrame(rows).sort_values(
        ["log_loss", "multiclass_brier", "c_value"], ignore_index=True
    )
    selected_c = float(tuning.iloc[0]["c_value"])
    tuning["selected"] = tuning["c_value"].eq(selected_c)
    selected_at_boundary = selected_c in {min(candidates), max(candidates)}
    tuning["selection_at_search_boundary"] = (
        tuning["selected"] & selected_at_boundary
    )
    return selected_c, tuning


def tune_temporal_models(
    frame: pd.DataFrame,
    validation_years: Iterable[int],
    c_values: Iterable[float],
    feature_modes: Iterable[str] = FEATURE_MODES,
    log_loss_tolerance: float = 0.001,
) -> tuple[str, float, pd.DataFrame, pd.DataFrame]:
    """Compare feature modes and C values with rolling-origin validation."""

    years = sorted({int(year) for year in validation_years})
    candidates = sorted({float(value) for value in c_values})
    modes = list(dict.fromkeys(feature_modes))
    if not years:
        raise ValueError("시간검증 연도가 하나 이상 필요합니다.")
    if not candidates:
        raise ValueError("비교할 C 후보가 하나 이상 필요합니다.")
    if not np.isfinite(candidates).all() or any(value <= 0 for value in candidates):
        raise ValueError("모든 C 후보는 유한한 양수여야 합니다.")
    if not np.isfinite(log_loss_tolerance) or log_loss_tolerance < 0:
        raise ValueError("Log Loss 허용오차는 유한한 0 이상의 값이어야 합니다.")
    invalid_modes = sorted(set(modes) - set(FEATURE_MODES))
    if invalid_modes:
        raise ValueError(f"지원하지 않는 피처 모드입니다: {invalid_modes}")

    fold_rows: list[dict[str, Any]] = []
    for feature_mode in modes:
        for validation_year in years:
            train = frame.loc[frame["survey_year"] < validation_year].copy()
            validation = frame.loc[
                frame["survey_year"].eq(validation_year)
            ].copy()
            if train.empty or validation.empty:
                raise ValueError(
                    "시간검증 학습 또는 검증자료가 비어 있습니다: "
                    f"validation_year={validation_year}"
                )
            validate_model_class_coverage(
                train,
                context=f"시간검증 {validation_year}년 학습",
            )
            validate_model_class_coverage(
                validation,
                context=f"시간검증 {validation_year}년 검증",
            )
            training_years = sorted(train["survey_year"].unique().tolist())
            for c_value in candidates:
                model = fit_multinomial_model(
                    train,
                    c_value,
                    feature_mode=feature_mode,
                )
                metrics, _ = evaluate_model(model, validation)
                fold_rows.append(
                    {
                        "feature_mode": feature_mode,
                        "c_value": c_value,
                        "training_years": "-".join(map(str, training_years)),
                        "validation_year": validation_year,
                        **metrics,
                    }
                )

    folds = pd.DataFrame(fold_rows)
    metric_columns = [
        "accuracy",
        "top3_accuracy",
        "log_loss",
        "log_loss_score",
        "log_loss_probability_score",
        "multiclass_brier",
        "macro_f1",
        "distribution_match_score",
        "mean_category_error_pp",
    ]
    named_aggregations: dict[str, tuple[str, str]] = {}
    for column in metric_columns:
        named_aggregations[f"mean_{column}"] = (column, "mean")
    named_aggregations["std_log_loss"] = ("log_loss", "std")
    named_aggregations["worst_log_loss"] = ("log_loss", "max")
    summary = (
        folds.groupby(["feature_mode", "c_value"], as_index=False)
        .agg(**named_aggregations)
        .sort_values(
            ["mean_log_loss", "mean_multiclass_brier", "c_value"],
            ignore_index=True,
        )
    )
    best_log_loss = float(summary["mean_log_loss"].min())
    summary["within_log_loss_tolerance"] = summary["mean_log_loss"].le(
        best_log_loss + log_loss_tolerance
    )
    mode_order = {mode: index for index, mode in enumerate(modes)}
    eligible = summary.loc[summary["within_log_loss_tolerance"]].copy()
    eligible["feature_mode_order"] = eligible["feature_mode"].map(mode_order)
    selected_row = eligible.sort_values(
        ["feature_mode_order", "c_value"], ignore_index=True
    ).iloc[0]
    selected_mode = str(selected_row["feature_mode"])
    selected_c = float(selected_row["c_value"])
    summary["selected"] = summary["feature_mode"].eq(selected_mode) & summary[
        "c_value"
    ].eq(selected_c)
    selected_mode_candidates = summary.loc[
        summary["feature_mode"].eq(selected_mode), "c_value"
    ]
    selected_at_boundary = selected_c in {
        float(selected_mode_candidates.min()),
        float(selected_mode_candidates.max()),
    }
    summary["selection_at_search_boundary"] = (
        summary["selected"] & selected_at_boundary
    )
    return selected_mode, selected_c, summary, folds


def tune_grouped_models(
    frame: pd.DataFrame,
    c_values: Iterable[float],
    feature_modes: Iterable[str] = FEATURE_MODES,
    n_splits: int = 5,
    random_state: int = 42,
    log_loss_tolerance: float = 0.001,
) -> tuple[str, float, pd.DataFrame, pd.DataFrame]:
    """Tune with year-stratified respondent-group cross-validation.

    Each respondent is assigned to exactly one fold.  Assignment is shuffled
    separately within each survey year, so every fold contains respondents
    from 2021~2024 without leaking a respondent's category rows across splits.
    """

    if RESPONDENT_COLUMN not in frame.columns:
        raise ValueError(f"그룹 교차검증에 {RESPONDENT_COLUMN} 열이 필요합니다.")
    if not isinstance(n_splits, int) or n_splits < 2:
        raise ValueError("그룹 교차검증 fold 수는 2 이상의 정수여야 합니다.")
    candidates = sorted({float(value) for value in c_values})
    modes = list(dict.fromkeys(feature_modes))
    if not candidates:
        raise ValueError("비교할 C 후보가 하나 이상 필요합니다.")
    if not np.isfinite(candidates).all() or any(value <= 0 for value in candidates):
        raise ValueError("모든 C 후보는 유한한 양수여야 합니다.")
    if not np.isfinite(log_loss_tolerance) or log_loss_tolerance < 0:
        raise ValueError("Log Loss 허용오차는 유한한 0 이상의 값이어야 합니다.")
    invalid_modes = sorted(set(modes) - set(FEATURE_MODES))
    if invalid_modes:
        raise ValueError(f"지원하지 않는 피처 모드입니다: {invalid_modes}")

    respondents = frame[[RESPONDENT_COLUMN, "survey_year"]].drop_duplicates()
    respondent_year_counts = respondents.groupby(RESPONDENT_COLUMN)[
        "survey_year"
    ].nunique()
    if respondent_year_counts.gt(1).any():
        raise ValueError("한 응답자 식별자가 여러 조사연도에 존재합니다.")

    rng = np.random.default_rng(random_state)
    assignment_parts: list[pd.DataFrame] = []
    for survey_year, group in respondents.groupby("survey_year", sort=True):
        respondent_ids = group[RESPONDENT_COLUMN].to_numpy(copy=True)
        if len(respondent_ids) < n_splits:
            raise ValueError(
                f"{survey_year}년 응답자 수가 {n_splits}-Fold보다 적습니다."
            )
        rng.shuffle(respondent_ids)
        assignment_parts.append(
            pd.DataFrame(
                {
                    RESPONDENT_COLUMN: respondent_ids,
                    "cv_fold": np.arange(len(respondent_ids)) % n_splits,
                }
            )
        )
    assignments = pd.concat(assignment_parts, ignore_index=True)
    fold_lookup = assignments.set_index(RESPONDENT_COLUMN)["cv_fold"]
    working = frame.copy()
    working["cv_fold"] = working[RESPONDENT_COLUMN].map(fold_lookup)
    if working["cv_fold"].isna().any():
        raise ValueError("일부 응답자에 그룹 교차검증 fold가 배정되지 않았습니다.")
    working["cv_fold"] = working["cv_fold"].astype(int)

    fold_rows: list[dict[str, Any]] = []
    for feature_mode in modes:
        for fold in range(n_splits):
            train = working.loc[working["cv_fold"].ne(fold)].copy()
            validation = working.loc[working["cv_fold"].eq(fold)].copy()
            train_respondents = set(train[RESPONDENT_COLUMN].unique())
            validation_respondents = set(validation[RESPONDENT_COLUMN].unique())
            if train_respondents & validation_respondents:
                raise ValueError("그룹 교차검증에서 응답자 누출이 발생했습니다.")
            validate_model_class_coverage(
                train,
                context=f"그룹 교차검증 {fold + 1}번 학습",
            )
            validate_model_class_coverage(
                validation,
                context=f"그룹 교차검증 {fold + 1}번 검증",
            )
            for c_value in candidates:
                model = fit_multinomial_model(
                    train,
                    c_value,
                    feature_mode=feature_mode,
                )
                metrics, _ = evaluate_model(model, validation)
                fold_rows.append(
                    {
                        "feature_mode": feature_mode,
                        "c_value": c_value,
                        "cv_fold": fold + 1,
                        "training_years": "-".join(
                            map(str, sorted(train["survey_year"].unique()))
                        ),
                        "validation_years": "-".join(
                            map(str, sorted(validation["survey_year"].unique()))
                        ),
                        "train_respondents": len(train_respondents),
                        "validation_respondents": len(validation_respondents),
                        **metrics,
                    }
                )

    folds = pd.DataFrame(fold_rows)
    metric_columns = [
        "accuracy",
        "top3_accuracy",
        "log_loss",
        "log_loss_score",
        "log_loss_probability_score",
        "multiclass_brier",
        "macro_f1",
        "distribution_match_score",
        "mean_category_error_pp",
    ]
    named_aggregations = {
        f"mean_{column}": (column, "mean") for column in metric_columns
    }
    named_aggregations["std_log_loss"] = ("log_loss", "std")
    named_aggregations["worst_log_loss"] = ("log_loss", "max")
    summary = (
        folds.groupby(["feature_mode", "c_value"], as_index=False)
        .agg(**named_aggregations)
        .sort_values(
            ["mean_log_loss", "mean_multiclass_brier", "c_value"],
            ignore_index=True,
        )
    )
    best_log_loss = float(summary["mean_log_loss"].min())
    summary["within_log_loss_tolerance"] = summary["mean_log_loss"].le(
        best_log_loss + log_loss_tolerance
    )
    mode_order = {mode: index for index, mode in enumerate(modes)}
    eligible = summary.loc[summary["within_log_loss_tolerance"]].copy()
    eligible["feature_mode_order"] = eligible["feature_mode"].map(mode_order)
    selected_row = eligible.sort_values(
        ["feature_mode_order", "c_value"], ignore_index=True
    ).iloc[0]
    selected_mode = str(selected_row["feature_mode"])
    selected_c = float(selected_row["c_value"])
    summary["selected"] = summary["feature_mode"].eq(selected_mode) & summary[
        "c_value"
    ].eq(selected_c)
    selected_mode_candidates = summary.loc[
        summary["feature_mode"].eq(selected_mode), "c_value"
    ]
    selected_at_boundary = selected_c in {
        float(selected_mode_candidates.min()),
        float(selected_mode_candidates.max()),
    }
    summary["selection_at_search_boundary"] = (
        summary["selected"] & selected_at_boundary
    )
    return selected_mode, selected_c, summary, folds


def select_combined_validation_model(
    temporal_summary: pd.DataFrame,
    grouped_summary: pd.DataFrame,
    feature_modes: Iterable[str] = FEATURE_MODES,
    log_loss_tolerance: float = 0.001,
) -> tuple[str, float, pd.DataFrame]:
    """Select one model by equally weighting temporal and grouped Log Loss."""

    keys = ["feature_mode", "c_value"]
    required_metrics = [
        "mean_log_loss",
        "mean_log_loss_score",
        "mean_multiclass_brier",
        "mean_top3_accuracy",
        "selected",
    ]
    for label, summary in (
        ("temporal", temporal_summary),
        ("grouped", grouped_summary),
    ):
        missing = sorted(set([*keys, *required_metrics]) - set(summary.columns))
        if missing:
            raise ValueError(f"{label} 검증 요약에 필요한 열이 없습니다: {missing}")
    if not np.isfinite(log_loss_tolerance) or log_loss_tolerance < 0:
        raise ValueError("Log Loss 허용오차는 유한한 0 이상의 값이어야 합니다.")

    temporal = temporal_summary[[*keys, *required_metrics]].rename(
        columns={column: f"temporal_{column}" for column in required_metrics}
    )
    grouped = grouped_summary[[*keys, *required_metrics]].rename(
        columns={column: f"grouped_{column}" for column in required_metrics}
    )
    combined = temporal.merge(grouped, on=keys, how="inner", validate="one_to_one")
    if len(combined) != len(temporal_summary) or len(combined) != len(grouped_summary):
        raise ValueError("시간검증과 그룹검증의 모델 후보가 일치하지 않습니다.")

    combined["combined_mean_log_loss"] = combined[
        ["temporal_mean_log_loss", "grouped_mean_log_loss"]
    ].mean(axis=1)
    combined["combined_log_loss_score"] = 100.0 * np.exp(
        -combined["combined_mean_log_loss"]
    )
    combined["combined_mean_multiclass_brier"] = combined[
        ["temporal_mean_multiclass_brier", "grouped_mean_multiclass_brier"]
    ].mean(axis=1)
    combined["combined_mean_top3_accuracy"] = combined[
        ["temporal_mean_top3_accuracy", "grouped_mean_top3_accuracy"]
    ].mean(axis=1)
    best_log_loss = float(combined["combined_mean_log_loss"].min())
    combined["within_log_loss_tolerance"] = combined[
        "combined_mean_log_loss"
    ].le(best_log_loss + log_loss_tolerance)

    modes = list(dict.fromkeys(feature_modes))
    invalid_modes = sorted(set(combined["feature_mode"]) - set(modes))
    if invalid_modes:
        raise ValueError(f"결합 검증에 정의되지 않은 피처 모드가 있습니다: {invalid_modes}")
    mode_order = {mode: index for index, mode in enumerate(modes)}
    eligible = combined.loc[combined["within_log_loss_tolerance"]].copy()
    eligible["feature_mode_order"] = eligible["feature_mode"].map(mode_order)
    selected_row = eligible.sort_values(
        ["feature_mode_order", "c_value"], ignore_index=True
    ).iloc[0]
    selected_mode = str(selected_row["feature_mode"])
    selected_c = float(selected_row["c_value"])
    combined["selected"] = combined["feature_mode"].eq(selected_mode) & combined[
        "c_value"
    ].eq(selected_c)
    selected_mode_candidates = combined.loc[
        combined["feature_mode"].eq(selected_mode), "c_value"
    ]
    selected_at_boundary = selected_c in {
        float(selected_mode_candidates.min()),
        float(selected_mode_candidates.max()),
    }
    combined["selection_at_search_boundary"] = (
        combined["selected"] & selected_at_boundary
    )
    return (
        selected_mode,
        selected_c,
        combined.sort_values(
            ["combined_mean_log_loss", "combined_mean_multiclass_brier", "c_value"],
            ignore_index=True,
        ),
    )


def build_sex_age_probability_table(
    model: Pipeline,
    survey_year: int,
) -> pd.DataFrame:
    """Predict all model categories for every valid sex-by-age population cell."""

    cells = pd.MultiIndex.from_product(
        [sorted(SEX_LABELS), sorted(AGE_LABELS)], names=["sex_code", "age_code"]
    ).to_frame(index=False)
    cells["sex_age_code"] = (
        cells["sex_code"].astype("string")
        + "_"
        + cells["age_code"].astype("string")
    )
    cells["survey_year"] = int(survey_year)
    classes = model.named_steps["classifier"].classes_
    probabilities = model.predict_proba(cells[list(MODEL_FEATURES)])

    probability_frame = pd.DataFrame(probabilities, columns=classes)
    wide = pd.concat([cells, probability_frame], axis=1)
    long = wide.melt(
        id_vars=[*MODEL_FEATURES],
        value_vars=list(classes),
        var_name=TARGET_COLUMN,
        value_name="preference_probability",
    )
    if OTHER_CATEGORY not in set(long[TARGET_COLUMN]):
        raise ValueError(
            f"절대확률과 조건부 구성비 계산에 필요한 '{OTHER_CATEGORY}' "
            "클래스가 모델에 없습니다."
        )
    long["preference_probability_absolute"] = long["preference_probability"]
    group_keys = ["sex_code", "age_code"]
    other_probability = (
        long.loc[long[TARGET_COLUMN].eq(OTHER_CATEGORY)]
        .set_index(group_keys)["preference_probability_absolute"]
    )
    long["other_probability_absolute"] = pd.MultiIndex.from_frame(
        long[group_keys]
    ).map(other_probability)
    policy_mask = long[TARGET_COLUMN].isin(PREFERENCE_OUTPUT_CATEGORIES)
    policy_denominator = 1.0 - long["other_probability_absolute"]
    if (policy_denominator <= 0).any() or not np.isfinite(
        policy_denominator.to_numpy(dtype=float)
    ).all():
        raise ValueError("기타확률 때문에 정책 9개 분야 조건부 구성비를 계산할 수 없습니다.")
    long["preference_share_conditional_mnc"] = np.where(
        policy_mask,
        long["preference_probability_absolute"] / policy_denominator,
        np.nan,
    )
    long["is_policy_category"] = policy_mask
    long.insert(1, "sex_label", long["sex_code"].map(SEX_LABELS))
    long.insert(3, "age_label", long["age_code"].map(AGE_LABELS))
    sums = long.groupby(["sex_code", "age_code"], observed=False)[
        "preference_probability"
    ].sum()
    if not np.allclose(sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError("성별×연령별 중분류 선호확률 합이 1이 아닙니다.")
    conditional_sums = long.loc[policy_mask].groupby(
        group_keys, observed=False
    )["preference_share_conditional_mnc"].sum()
    if not np.allclose(conditional_sums.to_numpy(), 1.0, atol=1e-8):
        raise ValueError("성별×연령별 정책 9개 분야 조건부 구성비 합이 1이 아닙니다.")
    return long.sort_values(
        ["sex_code", "age_code", TARGET_COLUMN], ignore_index=True
    )


def build_group_calibration_table(
    model: Pipeline,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Compare weighted observed and predicted rates within sex-age cells."""

    working = frame.reset_index(drop=True)
    classes = model.named_steps["classifier"].classes_
    probabilities = model.predict_proba(working[list(MODEL_FEATURES)])
    parts: list[pd.DataFrame] = []
    for (sex_code, age_code), index in working.groupby(
        ["sex_code", "age_code"], observed=False
    ).groups.items():
        group = working.loc[index].reset_index(drop=True)
        group_probabilities = probabilities[np.asarray(index, dtype=int)]
        _, detail = evaluate_probabilities(group, group_probabilities, classes)
        detail.insert(0, "age_label", AGE_LABELS[int(age_code)])
        detail.insert(0, "age_code", int(age_code))
        detail.insert(0, "sex_label", SEX_LABELS[int(sex_code)])
        detail.insert(0, "sex_code", int(sex_code))
        detail["n_rows"] = len(group)
        parts.append(detail)
    return pd.concat(parts, ignore_index=True)


def extract_model_coefficients(model: Pipeline) -> pd.DataFrame:
    """Return softmax coefficients in the transformed feature space."""

    preprocessor = model.named_steps["preprocessor"]
    classifier = model.named_steps["classifier"]
    feature_names = preprocessor.get_feature_names_out()
    rows: list[dict[str, Any]] = []
    for class_index, category in enumerate(classifier.classes_):
        rows.append(
            {
                TARGET_COLUMN: category,
                "feature": "intercept",
                "coefficient": float(classifier.intercept_[class_index]),
            }
        )
        for feature, coefficient in zip(
            feature_names, classifier.coef_[class_index], strict=True
        ):
            rows.append(
                {
                    TARGET_COLUMN: category,
                    "feature": str(feature),
                    "coefficient": float(coefficient),
                }
            )
    return pd.DataFrame(rows)
