from __future__ import annotations

import hashlib
import json
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

from preference_analysis.inference import (  # noqa: E402
    build_accessibility_category_contract,
    build_deployment_pipeline,
    build_h3sfca_demand_table,
    load_preference_pipeline,
    merge_preference_with_h3sfca,
    predict_probability_frame,
    predict_proba_class_order,
    prepare_prediction_input,
)
from preference_analysis.mapping import (  # noqa: E402
    MODEL_CATEGORIES,
    PREFERENCE_OUTPUT_CATEGORIES,
)
from preference_analysis.modeling import (  # noqa: E402
    INTERACTION_FEATURE_MODE,
    MODEL_FEATURES,
    TARGET_COLUMN,
    build_multinomial_pipeline,
)


def synthetic_fitted_model():
    rows: list[dict[str, object]] = []
    for sex_code in (1, 2):
        for age_code in range(1, 8):
            for category in MODEL_CATEGORIES:
                rows.append(
                    {
                        "sex_code": sex_code,
                        "age_code": age_code,
                        "sex_age_code": f"{sex_code}_{age_code}",
                        "survey_year": 2024,
                        TARGET_COLUMN: category,
                    }
                )
    frame = pd.DataFrame(rows)
    model = build_multinomial_pipeline(
        c_value=0.1,
        feature_mode=INTERACTION_FEATURE_MODE,
    )
    model.fit(frame[list(MODEL_FEATURES)], frame[TARGET_COLUMN])
    return model


def synthetic_grid_preference() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, category in enumerate(PREFERENCE_OUTPUT_CATEGORIES, start=1):
        rows.append(
            {
                "GRID_CD": "G1",
                "middle_category": category,
                "preference_probability_absolute": index / 100,
                "potential_demand_absolute": float(index),
                "preference_share_conditional_mnc": 1
                / len(PREFERENCE_OUTPUT_CATEGORIES),
                "other_probability_absolute": 0.4,
            }
        )
    return pd.DataFrame(rows)


class PreferenceInferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fitted_model = synthetic_fitted_model()
        cls.deployment_model = build_deployment_pipeline(cls.fitted_model)

    def test_raw_input_adapter_matches_original_fitted_pipeline(self) -> None:
        raw = pd.DataFrame(
            [
                {"GRID_CD": "G1", "sex_code": 1, "age_code": 2, "survey_year": 2024},
                {"GRID_CD": "G2", "sex_code": 2, "age_code": 7, "survey_year": 2025},
            ]
        )
        prepared = prepare_prediction_input(raw)
        expected = self.fitted_model.predict_proba(prepared)
        actual = self.deployment_model.predict_proba(raw)
        np.testing.assert_allclose(actual, expected, atol=1e-12)
        self.assertEqual(prepared["sex_age_code"].tolist(), ["1_2", "2_7"])

    def test_labeled_output_uses_exact_predict_proba_class_order(self) -> None:
        raw = pd.DataFrame(
            [{"example_id": "A", "sex_code": 1, "age_code": 3, "survey_year": 2024}]
        )
        output = predict_probability_frame(self.deployment_model, raw)
        classes = predict_proba_class_order(self.deployment_model)
        probability_columns = [f"probability__{category}" for category in classes]
        self.assertEqual(output.columns[-len(classes) :].tolist(), probability_columns)
        self.assertAlmostEqual(float(output[probability_columns].sum(axis=1).iloc[0]), 1.0)
        self.assertEqual(output.loc[0, "example_id"], "A")

    def test_invalid_raw_input_is_rejected(self) -> None:
        cases = (
            (
                pd.DataFrame([{"sex_code": 1, "age_code": 2}]),
                "누락",
            ),
            (
                pd.DataFrame([{"sex_code": 3, "age_code": 2, "survey_year": 2024}]),
                "성별",
            ),
            (
                pd.DataFrame([{"sex_code": 1, "age_code": 8, "survey_year": 2024}]),
                "연령",
            ),
            (
                pd.DataFrame([{"sex_code": 1, "age_code": 2, "survey_year": 2026}]),
                "조사연도",
            ),
            (
                pd.DataFrame([{"sex_code": 1, "age_code": np.inf, "survey_year": 2024}]),
                "유한",
            ),
        )
        for frame, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex((ValueError, TypeError), message):
                    self.deployment_model.predict_proba(frame)


class AccessibilityHandoffTest(unittest.TestCase):
    def test_category_contract_has_eight_supported_and_two_na_categories(self) -> None:
        contract = build_accessibility_category_contract()
        supported = contract.loc[contract["merge_allowed"]]
        unsupported = contract.loc[~contract["merge_allowed"]]
        self.assertEqual(set(supported["accessibility_middle_category"]), set(PREFERENCE_OUTPUT_CATEGORIES))
        self.assertEqual(
            set(unsupported["accessibility_middle_category"]),
            {"음악", "체육용품"},
        )
        self.assertTrue(unsupported["preference_middle_category"].isna().all())
        self.assertTrue(unsupported["missing_value_policy"].eq("NA_not_zero").all())

    def test_h3sfca_demand_uses_absolute_potential_demand(self) -> None:
        demand = build_h3sfca_demand_table(synthetic_grid_preference())
        self.assertEqual(set(demand["중분류"]), set(PREFERENCE_OUTPUT_CATEGORIES))
        np.testing.assert_allclose(
            demand.sort_values("수요인구수")["수요인구수"],
            np.arange(1, len(PREFERENCE_OUTPUT_CATEGORIES) + 1, dtype=float),
        )

    def test_merge_preserves_unsupported_categories_as_na(self) -> None:
        access_rows = []
        for category in [*PREFERENCE_OUTPUT_CATEGORIES, "음악", "체육용품"]:
            access_rows.append(
                {
                    "접근수단": "도보" if category not in {"공연", "관광지", "미술", "스포츠관람"} else "대중교통",
                    "GRID_CD": "G1",
                    "중분류": category,
                    "H3SFCA_접근성": 0.1,
                }
            )
        merged = merge_preference_with_h3sfca(
            pd.DataFrame(access_rows),
            synthetic_grid_preference(),
        )
        supported = merged["merge_allowed"]
        self.assertTrue(merged.loc[supported, "potential_demand_absolute"].notna().all())
        self.assertTrue(merged.loc[~supported, "potential_demand_absolute"].isna().all())


class TrackedHandoffArtifactTest(unittest.TestCase):
    def test_bundle_contract_and_examples_match_joblib(self) -> None:
        bundle = PROJECT_ROOT / "models/preference_analysis/v1"
        model_path = bundle / "preference_model_pipeline.joblib"
        contract_path = bundle / "model_contract.json"
        example_input_path = bundle / "example_input.csv"
        example_output_path = bundle / "example_output.csv"
        requirements_path = bundle / "requirements.txt"
        for path in (
            model_path,
            contract_path,
            example_input_path,
            example_output_path,
            requirements_path,
        ):
            self.assertTrue(path.is_file(), path)

        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        self.assertEqual(digest, contract["model_artifact"]["sha256"])

        model = load_preference_pipeline(model_path)
        actual_classes = list(predict_proba_class_order(model))
        contract_classes = [
            row["middle_category"]
            for row in contract["predict_proba_contract"]["class_order"]
        ]
        self.assertEqual(actual_classes, contract_classes)

        requirements = requirements_path.read_text(encoding="utf-8").splitlines()
        self.assertIn(
            f"scikit-learn=={contract['runtime']['scikit_learn']}",
            requirements,
        )
        self.assertEqual(
            hashlib.sha256(requirements_path.read_bytes()).hexdigest(),
            contract["files"][requirements_path.name]["sha256"],
        )

        example_input = pd.read_csv(example_input_path, encoding="utf-8-sig")
        expected = pd.read_csv(example_output_path, encoding="utf-8-sig")
        actual = predict_probability_frame(model, example_input)
        self.assertEqual(actual.columns.tolist(), expected.columns.tolist())
        probability_columns = [
            column for column in actual.columns if column.startswith("probability__")
        ]
        np.testing.assert_allclose(
            actual[probability_columns],
            expected[probability_columns],
            atol=1e-12,
        )


if __name__ == "__main__":
    unittest.main()
