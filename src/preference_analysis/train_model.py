"""Train and validate the satisfaction-based multinomial preference model."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from .build_mapping import find_project_root
from .mapping import (
    MODEL_CATEGORIES,
    PREFERENCE_OUTPUT_CATEGORIES,
    UNMODELED_PREFERENCE_CATEGORIES,
)
from .modeling import (
    ADDITIVE_FEATURE_MODE,
    BASE_WEIGHT_COLUMN,
    FEATURE_MODES,
    INTERACTION_FEATURE_MODE,
    RANK_SCORES,
    RESPONDENT_COLUMN,
    TARGET_COLUMN,
    build_group_calibration_table,
    build_sex_age_probability_table,
    evaluate_model,
    evaluate_probabilities,
    extract_model_coefficients,
    fit_multinomial_model,
    prepare_model_frame,
    select_combined_validation_model,
    tune_grouped_models,
    tune_regularization,
    tune_temporal_models,
    validate_model_class_coverage,
    weighted_class_prior,
)


DEFAULT_C_VALUES: tuple[float, ...] = (
    0.0001,
    0.0003,
    0.001,
    0.003,
    0.01,
    0.03,
    0.1,
    0.3,
    1.0,
    3.0,
    10.0,
    30.0,
    100.0,
)
TEMPORAL_VALIDATION_YEARS: tuple[int, ...] = (2022, 2023, 2024)
GROUPED_CV_FOLDS = 5
GROUPED_CV_RANDOM_STATE = 42
LOG_LOSS_SELECTION_TOLERANCE = 0.001
FINAL_FEATURE_MODE_PREFERENCE: tuple[str, ...] = (
    INTERACTION_FEATURE_MODE,
    ADDITIVE_FEATURE_MODE,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument(
        "--c-values",
        type=float,
        nargs="+",
        default=list(DEFAULT_C_VALUES),
        help=(
            "2022~2024년 순차검증과 2021~2024년 응답자 5-Fold에서 "
            "비교할 L2 규제강도 C 후보"
        ),
    )
    return parser


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def baseline_evaluation(
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    classes: np.ndarray,
) -> tuple[dict[str, float | int], pd.DataFrame]:
    prior = weighted_class_prior(train, classes)
    probabilities = np.tile(prior, (len(evaluation), 1))
    return evaluate_probabilities(evaluation, probabilities, classes)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def add_log_loss_skill_score(scores: pd.DataFrame) -> pd.DataFrame:
    """Add improvement over the weighted-prior baseline for each test year."""

    output = scores.copy()
    baseline = (
        output.loc[output["model"].eq("weighted_prior_baseline")]
        .set_index("evaluation_year")["log_loss"]
        .to_dict()
    )
    output["log_loss_skill_score_vs_baseline"] = output.apply(
        lambda row: 100.0
        * (1.0 - row["log_loss"] / baseline[int(row["evaluation_year"])]),
        axis=1,
    )
    return output


def split_model_periods(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Create fixed development/test periods and keep 2025 out of selection."""

    expected_years = {2021, 2022, 2023, 2024, 2025}
    actual_years = set(frame["survey_year"].unique())
    if actual_years != expected_years:
        raise ValueError(
            "모델 입력 조사연도가 2021~2025와 일치하지 않습니다: "
            f"actual={sorted(actual_years)}"
        )
    validate_model_class_coverage(frame, MODEL_CATEGORIES, context="2021~2025 전체")
    splits = {
        "train_2021_2023": frame.loc[
            frame["survey_year"].between(2021, 2023)
        ].copy(),
        "validation_2024": frame.loc[frame["survey_year"].eq(2024)].copy(),
        "train_2021_2024": frame.loc[
            frame["survey_year"].between(2021, 2024)
        ].copy(),
        "test_2025": frame.loc[frame["survey_year"].eq(2025)].copy(),
    }
    for label, split in splits.items():
        if split.empty:
            raise ValueError(f"{label} 자료가 비어 있습니다.")
        validate_model_class_coverage(split, MODEL_CATEGORIES, context=label)
    if 2025 in set(splits["train_2021_2024"]["survey_year"]):
        raise ValueError("2025년 평가자료가 모델 선택·최종 학습에 포함됐습니다.")
    return splits


def summarize_group_calibration(calibration: pd.DataFrame) -> pd.DataFrame:
    """Summarize sex-age calibration without fitting a post-hoc calibrator."""

    required = {
        "evaluation_year",
        "sex_code",
        "age_code",
        "middle_category",
        "absolute_difference_pp",
        "observed_weighted_count",
    }
    missing = sorted(required - set(calibration.columns))
    if missing:
        raise ValueError(f"calibration 요약에 필요한 열이 없습니다: {missing}")
    rows: list[dict[str, object]] = []
    for year, year_frame in calibration.groupby("evaluation_year", sort=True):
        group_summary = (
            year_frame.groupby(["sex_code", "age_code"], as_index=False)
            .agg(
                mean_absolute_error_pp=("absolute_difference_pp", "mean"),
                group_weight=("observed_weighted_count", "sum"),
            )
        )
        max_row = year_frame.loc[year_frame["absolute_difference_pp"].idxmax()]
        rows.append(
            {
                "evaluation_year": int(year),
                "weighted_mean_sex_age_calibration_error_pp": float(
                    np.average(
                        group_summary["mean_absolute_error_pp"],
                        weights=group_summary["group_weight"],
                    )
                ),
                "unweighted_mean_cell_category_error_pp": float(
                    year_frame["absolute_difference_pp"].mean()
                ),
                "maximum_cell_category_error_pp": float(
                    max_row["absolute_difference_pp"]
                ),
                "maximum_error_sex_code": int(max_row["sex_code"]),
                "maximum_error_age_code": int(max_row["age_code"]),
                "maximum_error_category": str(max_row["middle_category"]),
                "posthoc_calibration_applied": False,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = build_parser().parse_args()
    root = (args.project_root or find_project_root()).resolve()
    input_path = (
        root
        / "data/processed/preference_analysis/satisfaction_rank_middle_category_2021_2025.csv"
    )
    if not input_path.exists():
        raise FileNotFoundError(
            f"중분류 변환 데이터가 없습니다: {input_path}\n"
            "먼저 `python -m preference_analysis.build_mapping`을 실행하세요."
        )

    output_dir = root / "data/processed/preference_analysis/model"
    output_dir.mkdir(parents=True, exist_ok=True)

    mapped = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False)
    frame = prepare_model_frame(mapped)
    splits = split_model_periods(frame)
    train_2021_2023 = splits["train_2021_2023"]
    validation_2024 = splits["validation_2024"]
    train_2021_2024 = splits["train_2021_2024"]
    test_2025 = splits["test_2025"]

    temporal_selected_mode, temporal_selected_c, temporal_tuning, temporal_folds = (
        tune_temporal_models(
            frame,
            validation_years=TEMPORAL_VALIDATION_YEARS,
            c_values=args.c_values,
            feature_modes=FEATURE_MODES,
            log_loss_tolerance=LOG_LOSS_SELECTION_TOLERANCE,
        )
    )
    grouped_selected_mode, grouped_selected_c, grouped_tuning, grouped_folds = (
        tune_grouped_models(
            train_2021_2024,
            c_values=args.c_values,
            feature_modes=FEATURE_MODES,
            n_splits=GROUPED_CV_FOLDS,
            random_state=GROUPED_CV_RANDOM_STATE,
            log_loss_tolerance=LOG_LOSS_SELECTION_TOLERANCE,
        )
    )
    selected_mode, selected_c, combined_tuning = select_combined_validation_model(
        temporal_tuning,
        grouped_tuning,
        feature_modes=FINAL_FEATURE_MODE_PREFERENCE,
        log_loss_tolerance=LOG_LOSS_SELECTION_TOLERANCE,
    )
    _, tuning_2024 = tune_regularization(
        train_2021_2023,
        validation_2024,
        args.c_values,
        feature_mode=selected_mode,
    )
    tuning_2024["selected_combined_cv"] = tuning_2024["c_value"].eq(selected_c)

    score_rows: list[dict[str, object]] = []
    validation_detail: pd.DataFrame | None = None
    development_model = None
    for evaluation_year in TEMPORAL_VALIDATION_YEARS:
        rolling_train = frame.loc[frame["survey_year"] < evaluation_year].copy()
        rolling_test = frame.loc[frame["survey_year"].eq(evaluation_year)].copy()
        rolling_model = fit_multinomial_model(
            rolling_train,
            selected_c,
            feature_mode=selected_mode,
        )
        rolling_metrics, rolling_detail = evaluate_model(
            rolling_model,
            rolling_test,
        )
        rolling_classes = rolling_model.named_steps["classifier"].classes_
        rolling_baseline_metrics, _ = baseline_evaluation(
            rolling_train,
            rolling_test,
            rolling_classes,
        )
        training_years = sorted(rolling_train["survey_year"].unique().tolist())
        training_year_label = "-".join(map(str, training_years))
        score_rows.extend(
            [
                {
                    "evaluation_year": evaluation_year,
                    "training_years": training_year_label,
                    "model": "multinomial_logistic",
                    "feature_mode": selected_mode,
                    "c_value": selected_c,
                    **rolling_metrics,
                },
                {
                    "evaluation_year": evaluation_year,
                    "training_years": training_year_label,
                    "model": "weighted_prior_baseline",
                    "feature_mode": "weighted_prior",
                    "c_value": np.nan,
                    **rolling_baseline_metrics,
                },
            ]
        )
        if evaluation_year == 2024:
            validation_detail = rolling_detail
            development_model = rolling_model

    if validation_detail is None or development_model is None:
        raise RuntimeError("2024년 분야별 검증 결과가 생성되지 않았습니다.")

    final_model = fit_multinomial_model(
        train_2021_2024,
        selected_c,
        feature_mode=selected_mode,
    )
    test_metrics, test_detail = evaluate_model(final_model, test_2025)
    final_classes = final_model.named_steps["classifier"].classes_
    test_baseline_metrics, _ = baseline_evaluation(
        train_2021_2024, test_2025, final_classes
    )

    score_rows.extend(
        [
        {
            "evaluation_year": 2025,
            "training_years": "2021-2024",
            "model": "multinomial_logistic",
            "feature_mode": selected_mode,
            "c_value": selected_c,
            **test_metrics,
        },
        {
            "evaluation_year": 2025,
            "training_years": "2021-2024",
            "model": "weighted_prior_baseline",
            "feature_mode": "weighted_prior",
            "c_value": np.nan,
            **test_baseline_metrics,
        },
        ]
    )
    scores = add_log_loss_skill_score(pd.DataFrame(score_rows))

    validation_detail.insert(0, "evaluation_year", 2024)
    validation_detail.insert(1, "training_years", "2021-2023")
    test_detail.insert(0, "evaluation_year", 2025)
    test_detail.insert(1, "training_years", "2021-2024")

    sex_age_probabilities = build_sex_age_probability_table(final_model, 2024)
    calibration_2024 = build_group_calibration_table(
        development_model, validation_2024
    )
    calibration_2024.insert(0, "evaluation_year", 2024)
    calibration = build_group_calibration_table(final_model, test_2025)
    calibration.insert(0, "evaluation_year", 2025)
    calibration_summary = summarize_group_calibration(
        pd.concat([calibration_2024, calibration], ignore_index=True)
    )
    coefficients = extract_model_coefficients(final_model)

    tuning_path = output_dir / "multinomial_tuning_2024.csv"
    temporal_tuning_path = (
        output_dir / "multinomial_tuning_temporal_cv_2022_2024.csv"
    )
    temporal_fold_path = (
        output_dir / "multinomial_tuning_temporal_cv_by_fold_2022_2024.csv"
    )
    grouped_tuning_path = (
        output_dir / "multinomial_tuning_grouped_cv_2021_2024.csv"
    )
    grouped_fold_path = (
        output_dir / "multinomial_tuning_grouped_cv_by_fold_2021_2024.csv"
    )
    combined_tuning_path = output_dir / "multinomial_tuning_combined_cv.csv"
    temporal_score_path = output_dir / "model_score_temporal_2022_2025.csv"
    score_path = output_dir / "model_score_2024_2025.csv"
    validation_2024_path = output_dir / "model_validation_2024_by_category.csv"
    validation_2025_path = output_dir / "model_validation_2025_by_category.csv"
    calibration_path = output_dir / "model_calibration_by_sex_age_2025.csv"
    calibration_2024_path = output_dir / "model_calibration_by_sex_age_2024.csv"
    calibration_summary_path = (
        output_dir / "model_calibration_summary_2024_2025.csv"
    )
    probability_path = output_dir / "sex_age_middle_category_preference_2024.csv"
    coefficient_path = output_dir / "multinomial_coefficients_2021_2024.csv"
    model_path = output_dir / "multinomial_logistic_2021_2024.joblib"
    metadata_path = output_dir / "multinomial_model_metadata.json"

    write_csv(tuning_2024, tuning_path)
    write_csv(temporal_tuning, temporal_tuning_path)
    write_csv(temporal_folds, temporal_fold_path)
    write_csv(grouped_tuning, grouped_tuning_path)
    write_csv(grouped_folds, grouped_fold_path)
    write_csv(combined_tuning, combined_tuning_path)
    write_csv(scores, temporal_score_path)
    write_csv(scores.loc[scores["evaluation_year"].isin([2024, 2025])], score_path)
    write_csv(validation_detail, validation_2024_path)
    write_csv(test_detail, validation_2025_path)
    write_csv(calibration_2024, calibration_2024_path)
    write_csv(calibration, calibration_path)
    write_csv(calibration_summary, calibration_summary_path)
    write_csv(sex_age_probabilities, probability_path)
    write_csv(coefficients, coefficient_path)
    joblib.dump(final_model, model_path)

    code_paths = [
        Path(__file__).resolve(),
        root / "src/preference_analysis/modeling.py",
        root / "src/preference_analysis/mapping.py",
    ]
    metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(root),
        "python_version": platform.python_version(),
        "scikit_learn_version": sklearn.__version__,
        "input_file": str(input_path.relative_to(root)),
        "input_sha256": sha256(input_path),
        "code_files": [
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in code_paths
        ],
        "code_version_note": (
            "git_commit과 함께 실제 실행 코드 SHA-256을 기록하며, "
            "미커밋·미추적 상태에서는 code_files 해시가 재현 기준임"
        ),
        "target": "가장 만족스러운 여가활동 1~3순위의 순위가중 모델 중분류",
        "rank_scores": {str(rank): score for rank, score in RANK_SCORES.items()},
        "rank_weight_normalization": (
            "동일 중분류의 순위점수를 합산한 뒤 응답자 내부 합이 1이 되도록 정규화"
        ),
        "duplicate_middle_category_handling": (
            "응답자별 동일 중분류의 3:2:1 순위점수를 누적"
        ),
        "effective_weight": "최종가중치 × 응답자 내부 정규화 순위가중치",
        "future_preference_columns_used": False,
        "experience_target_interpretation": (
            "만족활동 기반 경험선호이며, 미래의 순수 희망이나 실제 이용자 예측이 아님"
        ),
        "preference_output_categories": list(PREFERENCE_OUTPUT_CATEGORIES),
        "unmodeled_preference_categories": sorted(
            UNMODELED_PREFERENCE_CATEGORIES
        ),
        "unmodeled_preference_handling": (
            "체육용품은 직접 선호확률을 산출하지 않으며 0으로 대체하지 않음; "
            "설문 활동은 전체 확률 보존을 위해 기타 선택지에만 포함하고, "
            "가맹점 공급·접근성 자료의 체육용품 분류는 유지"
        ),
        "probability_definitions": {
            "preference_probability": (
                "하위호환을 위한 10개 클래스 절대확률"
            ),
            "preference_probability_absolute": (
                "정책 9개 분야와 기타를 모두 보존한 절대확률 p(c)"
            ),
            "other_probability_absolute": "기타·문화누리 비대응 절대확률",
            "preference_share_conditional_mnc": (
                "정책 9개 분야 내 조건부 구성비 p(c)/(1-p(other)); "
                "절대 잠재수요 계산에 사용하지 않음"
            ),
        },
        "raw_prediction_features": ["sex_code", "age_code", "survey_year"],
        "derived_features": ["sex_age_code"],
        "selected_model_features": (
            ["sex_code", "age_code", "survey_year"]
            if selected_mode == ADDITIVE_FEATURE_MODE
            else ["sex_age_code", "survey_year"]
        ),
        "selected_feature_mode": selected_mode,
        "candidate_feature_modes": list(FEATURE_MODES),
        "final_feature_mode_preference": list(FINAL_FEATURE_MODE_PREFERENCE),
        "feature_mode_selection_rule": (
            "결합 Log Loss 최저값과 0.001 이내 후보 중 성별×연령 결합형을 "
            "우선하고, 같은 구조에서는 더 작은 C를 선택"
        ),
        "survey_weight": (
            "최종가중치 × 응답자 내부 순위가중치; 학습세트 평균 1로 정규화"
        ),
        "class_weight": None,
        "tuning_method": (
            "equal-weighted mean Log Loss of rolling-origin temporal validation "
            "and year-stratified respondent-group 5-Fold cross-validation"
        ),
        "tuning_validation_years": list(TEMPORAL_VALIDATION_YEARS),
        "temporal_validation_splits": [
            {"train": [2021], "validation": 2022},
            {"train": [2021, 2022], "validation": 2023},
            {"train": [2021, 2022, 2023], "validation": 2024},
        ],
        "grouped_cv_years": [2021, 2022, 2023, 2024],
        "grouped_cv_folds": GROUPED_CV_FOLDS,
        "grouped_cv_random_state": GROUPED_CV_RANDOM_STATE,
        "grouped_cv_split_unit": "respondent_id",
        "grouped_cv_year_stratified": True,
        "validation_combination_weight": {"temporal": 0.5, "grouped": 0.5},
        "temporal_selected_feature_mode": temporal_selected_mode,
        "temporal_selected_c": temporal_selected_c,
        "grouped_selected_feature_mode": grouped_selected_mode,
        "grouped_selected_c": grouped_selected_c,
        "temporal_grouped_selection_agreement": bool(
            temporal_selected_mode == grouped_selected_mode
            and temporal_selected_c == grouped_selected_c
        ),
        "log_loss_selection_tolerance": LOG_LOSS_SELECTION_TOLERANCE,
        "final_train_years": [2021, 2022, 2023, 2024],
        "final_test_year": 2025,
        "final_test_role": (
            "모델 선택에 사용하지 않은 시간 외 평가자료; "
            "기존 분석에서 반복 조회된 이력이 있어 pristine holdout으로 과장하지 않음"
        ),
        "accessibility_features_used": False,
        "activity_codebook_limit": (
            "통합자료의 공통 활동코드 체계를 사용했으며, "
            "2021~2023·2025 개별 코드북을 독립적으로 대조하지 못함"
        ),
        "selected_c": selected_c,
        "c_candidates": sorted({float(value) for value in args.c_values}),
        "selection_at_search_boundary": bool(
            combined_tuning.loc[
                combined_tuning["selected"], "selection_at_search_boundary"
            ].iloc[0]
        ),
        "classes": final_classes.tolist(),
        "model_row_counts": {
            "train_2021_2023": len(train_2021_2023),
            "validation_2024": len(validation_2024),
            "train_2021_2024": len(train_2021_2024),
            "test_2025": len(test_2025),
        },
        "row_counts": {
            "train_2021_2023": len(train_2021_2023),
            "validation_2024": len(validation_2024),
            "train_2021_2024": len(train_2021_2024),
            "test_2025": len(test_2025),
        },
        "respondent_counts": {
            "train_2021_2023": int(train_2021_2023[RESPONDENT_COLUMN].nunique()),
            "validation_2024": int(validation_2024[RESPONDENT_COLUMN].nunique()),
            "train_2021_2024": int(train_2021_2024[RESPONDENT_COLUMN].nunique()),
            "test_2025": int(test_2025[RESPONDENT_COLUMN].nunique()),
        },
        "base_survey_weight_column": BASE_WEIGHT_COLUMN,
        "classifier_iterations": final_model.named_steps[
            "classifier"
        ].n_iter_.tolist(),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"selected feature mode: {selected_mode}")
    print(f"selected C: {selected_c:g}")
    print(
        "individual validation selections: "
        f"temporal=({temporal_selected_mode}, C={temporal_selected_c:g}), "
        f"grouped=({grouped_selected_mode}, C={grouped_selected_c:g})"
    )
    print("\nTemporal tuning summary (2022-2024 rolling validation)")
    print(
        temporal_tuning[
            [
                "feature_mode",
                "c_value",
                "mean_log_loss",
                "mean_log_loss_score",
                "mean_log_loss_probability_score",
                "mean_multiclass_brier",
                "mean_top3_accuracy",
                "within_log_loss_tolerance",
                "selected",
            ]
        ]
        .sort_values(["feature_mode", "c_value"])
        .to_string(index=False)
    )
    print("\nCombined tuning summary (temporal 50% + grouped 50%)")
    print(
        combined_tuning[
            [
                "feature_mode",
                "c_value",
                "temporal_mean_log_loss",
                "grouped_mean_log_loss",
                "combined_mean_log_loss",
                "combined_log_loss_score",
                "combined_mean_top3_accuracy",
                "within_log_loss_tolerance",
                "selected",
            ]
        ]
        .sort_values(["feature_mode", "c_value"])
        .to_string(index=False)
    )
    print("\nmodel scores")
    print(
        scores[
            [
                "evaluation_year",
                "model",
                "accuracy",
                "top3_accuracy",
                "log_loss",
                "log_loss_score",
                "log_loss_probability_score",
                "log_loss_skill_score_vs_baseline",
                "multiclass_brier",
                "distribution_match_score",
                "mean_category_error_pp",
            ]
        ].to_string(index=False)
    )
    print("\noutputs")
    for path in (
        tuning_path,
        temporal_tuning_path,
        temporal_fold_path,
        grouped_tuning_path,
        grouped_fold_path,
        combined_tuning_path,
        temporal_score_path,
        score_path,
        validation_2024_path,
        validation_2025_path,
        calibration_path,
        calibration_2024_path,
        calibration_summary_path,
        probability_path,
        coefficient_path,
        model_path,
        metadata_path,
    ):
        print(path)


if __name__ == "__main__":
    main()
