from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) in sys.path:
    sys.path.remove(str(SRC_PATH))
sys.path.insert(0, str(SRC_PATH))

from preference_analysis.modeling import (  # noqa: E402
    BASE_WEIGHT_COLUMN,
    INTERACTION_FEATURE_MODE,
    MODEL_FEATURES,
    RANK_COLUMN,
    RANK_OCCURRENCE_COLUMN,
    RANK_SCORE_COLUMN,
    RANK_WEIGHT_COLUMN,
    RESPONDENT_COLUMN,
    TARGET_COLUMN,
    WEIGHT_COLUMN,
    build_group_calibration_table,
    build_sex_age_probability_table,
    evaluate_model,
    fit_multinomial_model,
    normalized_training_weights,
    prepare_model_frame,
    select_combined_validation_model,
    tune_grouped_models,
    tune_regularization,
    tune_temporal_models,
    validate_model_class_coverage,
)
from preference_analysis.train_model import (  # noqa: E402
    add_log_loss_skill_score,
    split_model_periods,
    summarize_group_calibration,
)
from preference_analysis.mapping import (  # noqa: E402
    MODEL_CATEGORIES,
    OTHER_CATEGORY,
    PREFERENCE_OUTPUT_CATEGORIES,
)


def synthetic_mapped_data() -> pd.DataFrame:
    categories = list(MODEL_CATEGORIES)
    rows: list[dict[str, object]] = []
    for year in range(2021, 2026):
        for sex in (1, 2):
            for age in range(1, 8):
                for repeat in range(3):
                    category_index = (year + sex + age + repeat) % len(categories)
                    category = categories[category_index]
                    rows.append(
                        {
                            "조사년도": year,
                            "성별": sex,
                            "연령": age,
                            "최종가중치": float(1 + repeat + age / 10),
                            "만족활동_1순위_중분류": category,
                            "만족활동_2순위_중분류": categories[
                                (category_index + 1) % len(categories)
                            ],
                            "만족활동_3순위_중분류": (
                                category
                                if repeat == 0
                                else categories[(category_index + 2) % len(categories)]
                            ),
                            "향후 희망하는 여가활동 1순위": 88,
                        }
                    )
    return pd.DataFrame(rows)


class ModelFrameTest(unittest.TestCase):
    def test_prepare_uses_all_satisfaction_ranks_and_ignores_future_columns(self) -> None:
        raw = synthetic_mapped_data()
        frame = prepare_model_frame(raw)
        self.assertGreater(len(frame), len(raw))
        self.assertNotIn("향후 희망하는 여가활동 1순위", frame.columns)
        self.assertEqual(set(frame[RANK_COLUMN]), {1, 2, 3})
        self.assertFalse(
            frame.duplicated([RESPONDENT_COLUMN, TARGET_COLUMN]).any()
        )

    def test_duplicate_category_accumulates_rank_scores_and_preserves_weight(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "source_row_index": 10,
                    "조사년도": 2024,
                    "성별": 1,
                    "연령": 3,
                    "최종가중치": 12.0,
                    "만족활동_1순위_중분류": "공연",
                    "만족활동_2순위_중분류": "영상",
                    "만족활동_3순위_중분류": "공연",
                }
            ]
        )
        frame = prepare_model_frame(raw)
        self.assertEqual(frame[TARGET_COLUMN].tolist(), ["공연", "영상"])
        self.assertEqual(frame[RANK_COLUMN].tolist(), [1, 2])
        np.testing.assert_allclose(frame[RANK_SCORE_COLUMN], [4.0, 2.0])
        np.testing.assert_array_equal(frame[RANK_OCCURRENCE_COLUMN], [2, 1])
        np.testing.assert_allclose(frame[RANK_WEIGHT_COLUMN], [4 / 6, 2 / 6])
        self.assertAlmostEqual(float(frame[WEIGHT_COLUMN].sum()), 12.0)

    def test_missing_lower_ranks_keep_full_respondent_weight(self) -> None:
        raw = synthetic_mapped_data().iloc[[0]].copy()
        raw["만족활동_2순위_중분류"] = pd.NA
        raw["만족활동_3순위_중분류"] = pd.NA
        frame = prepare_model_frame(raw)
        self.assertEqual(len(frame), 1)
        self.assertEqual(int(frame.iloc[0][RANK_COLUMN]), 1)
        self.assertEqual(float(frame.iloc[0][RANK_WEIGHT_COLUMN]), 1.0)
        self.assertEqual(
            float(frame.iloc[0][WEIGHT_COLUMN]),
            float(frame.iloc[0][BASE_WEIGHT_COLUMN]),
        )

    def test_respondent_effective_weights_equal_original_weights(self) -> None:
        raw = synthetic_mapped_data()
        frame = prepare_model_frame(raw)
        actual = frame.groupby(RESPONDENT_COLUMN)[WEIGHT_COLUMN].sum()
        expected = frame.groupby(RESPONDENT_COLUMN)[BASE_WEIGHT_COLUMN].first()
        np.testing.assert_allclose(actual.to_numpy(), expected.to_numpy())

    def test_training_weights_keep_ratios_and_mean_one(self) -> None:
        original = np.array([2.0, 4.0, 8.0])
        normalized = normalized_training_weights(original)
        self.assertAlmostEqual(float(normalized.mean()), 1.0)
        np.testing.assert_allclose(normalized / normalized[0], original / original[0])

    def test_nonpositive_weight_is_rejected(self) -> None:
        raw = synthetic_mapped_data()
        raw.loc[0, "최종가중치"] = 0
        with self.assertRaisesRegex(ValueError, "0보다 커야"):
            prepare_model_frame(raw)

    def test_nonfinite_weight_is_rejected(self) -> None:
        raw = synthetic_mapped_data()
        raw.loc[0, "최종가중치"] = np.inf
        with self.assertRaisesRegex(ValueError, "유한한 숫자"):
            prepare_model_frame(raw)

    def test_expected_policy_plus_other_class_coverage_is_enforced(self) -> None:
        frame = prepare_model_frame(synthetic_mapped_data())
        validate_model_class_coverage(frame)
        reduced = frame.loc[frame[TARGET_COLUMN].ne(OTHER_CATEGORY)]
        with self.assertRaisesRegex(ValueError, "클래스가 기대값과 다릅니다"):
            validate_model_class_coverage(reduced)

    def test_fixed_period_split_keeps_2025_out_of_training(self) -> None:
        splits = split_model_periods(prepare_model_frame(synthetic_mapped_data()))
        self.assertEqual(
            set(splits["train_2021_2024"]["survey_year"]),
            {2021, 2022, 2023, 2024},
        )
        self.assertEqual(set(splits["test_2025"]["survey_year"]), {2025})


class MultinomialModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frame = prepare_model_frame(synthetic_mapped_data())
        cls.train = cls.frame.loc[cls.frame["survey_year"].between(2021, 2023)]
        cls.validation = cls.frame.loc[cls.frame["survey_year"].eq(2024)]
        cls.model = fit_multinomial_model(cls.train, c_value=0.1)

    def test_probability_rows_sum_to_one(self) -> None:
        probabilities = self.model.predict_proba(
            self.validation[list(MODEL_FEATURES)]
        )
        np.testing.assert_allclose(probabilities.sum(axis=1), 1.0, atol=1e-8)

    def test_probability_outside_zero_one_is_rejected(self) -> None:
        probabilities = self.model.predict_proba(
            self.validation[list(MODEL_FEATURES)]
        )
        probabilities[0, 0] = -0.1
        probabilities[0, 1] += 0.1
        from preference_analysis.modeling import evaluate_probabilities

        with self.assertRaisesRegex(ValueError, "0 이상 1 이하"):
            evaluate_probabilities(
                self.validation,
                probabilities,
                self.model.named_steps["classifier"].classes_,
            )

    def test_metrics_have_valid_ranges(self) -> None:
        metrics, by_category = evaluate_model(self.model, self.validation)
        self.assertGreaterEqual(metrics["accuracy"], 0)
        self.assertLessEqual(metrics["accuracy"], 1)
        self.assertGreaterEqual(metrics["top3_accuracy"], metrics["accuracy"])
        self.assertGreaterEqual(metrics["distribution_match_score"], 0)
        self.assertLessEqual(metrics["distribution_match_score"], 100)
        self.assertAlmostEqual(
            metrics["log_loss_score"],
            100 * np.exp(-metrics["log_loss"]),
        )
        self.assertAlmostEqual(
            metrics["log_loss_probability_score"],
            metrics["log_loss_score"],
        )
        self.assertAlmostEqual(float(by_category["observed_rate"].sum()), 1.0)
        self.assertAlmostEqual(float(by_category["predicted_rate"].sum()), 1.0)

    def test_tuning_selects_one_candidate(self) -> None:
        selected_c, tuning = tune_regularization(
            self.train, self.validation, (0.1, 1.0)
        )
        self.assertIn(selected_c, (0.1, 1.0))
        self.assertEqual(int(tuning["selected"].sum()), 1)
        self.assertIn("train_log_loss", tuning)
        self.assertIn("log_loss_generalization_gap", tuning)
        self.assertIn("selection_at_search_boundary", tuning)
        expected_gap = tuning["log_loss"] - tuning["train_log_loss"]
        np.testing.assert_allclose(
            tuning["log_loss_generalization_gap"], expected_gap
        )

    def test_tuning_rejects_invalid_candidates(self) -> None:
        for candidates in ((), (0.0, 0.1), (-0.1, 0.1), (np.nan, 0.1)):
            with self.subTest(candidates=candidates):
                with self.assertRaisesRegex(ValueError, "C 후보"):
                    tune_regularization(self.train, self.validation, candidates)

    def test_sex_age_probability_table_is_complete(self) -> None:
        result = build_sex_age_probability_table(self.model, survey_year=2024)
        class_count = len(self.model.named_steps["classifier"].classes_)
        self.assertEqual(len(result), 2 * 7 * class_count)
        sums = result.groupby(["sex_code", "age_code"])[
            "preference_probability"
        ].sum()
        np.testing.assert_allclose(sums.to_numpy(), 1.0, atol=1e-8)
        self.assertTrue(
            {
                "preference_probability_absolute",
                "other_probability_absolute",
                "preference_share_conditional_mnc",
                "is_policy_category",
            }.issubset(result.columns)
        )
        np.testing.assert_allclose(
            result["preference_probability"],
            result["preference_probability_absolute"],
        )
        policy = result.loc[
            result[TARGET_COLUMN].isin(PREFERENCE_OUTPUT_CATEGORIES)
        ]
        conditional_sums = policy.groupby(["sex_code", "age_code"])[
            "preference_share_conditional_mnc"
        ].sum()
        np.testing.assert_allclose(conditional_sums.to_numpy(), 1.0, atol=1e-8)
        self.assertTrue(
            result.loc[
                result[TARGET_COLUMN].eq(OTHER_CATEGORY),
                "preference_share_conditional_mnc",
            ].isna().all()
        )

    def test_interaction_model_probability_rows_sum_to_one(self) -> None:
        model = fit_multinomial_model(
            self.train,
            c_value=0.1,
            feature_mode=INTERACTION_FEATURE_MODE,
        )
        probabilities = model.predict_proba(
            self.validation[list(MODEL_FEATURES)]
        )
        np.testing.assert_allclose(probabilities.sum(axis=1), 1.0, atol=1e-8)

    def test_temporal_tuning_compares_feature_modes(self) -> None:
        selected_mode, selected_c, summary, folds = tune_temporal_models(
            self.frame,
            validation_years=(2023, 2024),
            c_values=(0.1, 1.0),
        )
        self.assertIn(selected_mode, set(summary["feature_mode"]))
        self.assertIn(selected_c, (0.1, 1.0))
        self.assertEqual(int(summary["selected"].sum()), 1)
        self.assertIn("within_log_loss_tolerance", summary)
        self.assertIn("mean_log_loss_score", summary)
        self.assertEqual(set(folds["validation_year"]), {2023, 2024})

    def test_temporal_tuning_rejects_negative_log_loss_tolerance(self) -> None:
        with self.assertRaisesRegex(ValueError, "허용오차"):
            tune_temporal_models(
                self.frame,
                validation_years=(2023, 2024),
                c_values=(0.1,),
                log_loss_tolerance=-0.001,
            )

    def test_grouped_tuning_uses_five_respondent_disjoint_folds(self) -> None:
        train_2021_2024 = self.frame.loc[
            self.frame["survey_year"].between(2021, 2024)
        ]
        selected_mode, selected_c, summary, folds = tune_grouped_models(
            train_2021_2024,
            c_values=(0.1,),
            feature_modes=("additive",),
            n_splits=5,
            random_state=42,
        )
        self.assertEqual(selected_mode, "additive")
        self.assertEqual(selected_c, 0.1)
        self.assertEqual(int(summary["selected"].sum()), 1)
        self.assertEqual(set(folds["cv_fold"]), {1, 2, 3, 4, 5})
        self.assertEqual(set(folds["training_years"]), {"2021-2022-2023-2024"})
        self.assertEqual(set(folds["validation_years"]), {"2021-2022-2023-2024"})
        respondent_total = train_2021_2024[RESPONDENT_COLUMN].nunique()
        self.assertTrue(
            (
                folds["train_respondents"]
                + folds["validation_respondents"]
            ).eq(respondent_total).all()
        )

    def test_combined_validation_selects_one_shared_candidate(self) -> None:
        temporal_mode, temporal_c, temporal, _ = tune_temporal_models(
            self.frame,
            validation_years=(2023, 2024),
            c_values=(0.1, 1.0),
            feature_modes=("additive",),
        )
        self.assertEqual(temporal_mode, "additive")
        self.assertIn(temporal_c, (0.1, 1.0))
        grouped_mode, grouped_c, grouped, _ = tune_grouped_models(
            self.frame.loc[self.frame["survey_year"].between(2021, 2024)],
            c_values=(0.1, 1.0),
            feature_modes=("additive",),
            n_splits=3,
        )
        self.assertEqual(grouped_mode, "additive")
        self.assertIn(grouped_c, (0.1, 1.0))
        selected_mode, selected_c, combined = select_combined_validation_model(
            temporal,
            grouped,
            feature_modes=("additive",),
        )
        self.assertEqual(selected_mode, "additive")
        self.assertIn(selected_c, (0.1, 1.0))
        self.assertEqual(int(combined["selected"].sum()), 1)
        expected = combined[
            ["temporal_mean_log_loss", "grouped_mean_log_loss"]
        ].mean(axis=1)
        np.testing.assert_allclose(combined["combined_mean_log_loss"], expected)

    def test_combined_validation_can_prefer_interaction_within_tolerance(self) -> None:
        rows = []
        for feature_mode, loss in (
            ("additive", 1.5000),
            ("sex_age_interaction", 1.5004),
        ):
            rows.append(
                {
                    "feature_mode": feature_mode,
                    "c_value": 0.1,
                    "mean_log_loss": loss,
                    "mean_log_loss_score": 100 * np.exp(-loss),
                    "mean_multiclass_brier": 0.7,
                    "mean_top3_accuracy": 0.8,
                    "selected": feature_mode == "additive",
                }
            )
        temporal = pd.DataFrame(rows)
        grouped = pd.DataFrame(rows)
        selected_mode, selected_c, combined = select_combined_validation_model(
            temporal,
            grouped,
            feature_modes=("sex_age_interaction", "additive"),
            log_loss_tolerance=0.001,
        )
        self.assertEqual(selected_mode, "sex_age_interaction")
        self.assertEqual(selected_c, 0.1)
        self.assertEqual(int(combined["selected"].sum()), 1)

    def test_group_calibration_handles_nonzero_source_index(self) -> None:
        result = build_group_calibration_table(self.model, self.validation)
        class_count = len(self.model.named_steps["classifier"].classes_)
        self.assertEqual(len(result), 2 * 7 * class_count)
        self.assertFalse(result[["observed_rate", "predicted_rate"]].isna().any().any())

    def test_calibration_summary_and_log_loss_skill_formulas(self) -> None:
        calibration = build_group_calibration_table(self.model, self.validation)
        calibration.insert(0, "evaluation_year", 2024)
        summary = summarize_group_calibration(calibration)
        self.assertEqual(len(summary), 1)
        self.assertGreaterEqual(
            float(summary.iloc[0]["weighted_mean_sex_age_calibration_error_pp"]),
            0,
        )

        scores = pd.DataFrame(
            [
                {"evaluation_year": 2025, "model": "weighted_prior_baseline", "log_loss": 2.0},
                {"evaluation_year": 2025, "model": "multinomial_logistic", "log_loss": 1.5},
            ]
        )
        scored = add_log_loss_skill_score(scores)
        self.assertEqual(
            float(
                scored.loc[
                    scored["model"].eq("weighted_prior_baseline"),
                    "log_loss_skill_score_vs_baseline",
                ].iloc[0]
            ),
            0.0,
        )
        self.assertEqual(
            float(
                scored.loc[
                    scored["model"].eq("multinomial_logistic"),
                    "log_loss_skill_score_vs_baseline",
                ].iloc[0]
            ),
            25.0,
        )


if __name__ == "__main__":
    unittest.main()
