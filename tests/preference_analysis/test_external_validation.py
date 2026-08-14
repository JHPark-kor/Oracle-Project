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

from preference_analysis.external_validation import (  # noqa: E402
    ARTS_POPULATION_SCOPE,
    ARTS_ATTENDANCE_COLUMNS,
    CARD_VALIDATION_CROSSWALK,
    EXCLUDED_CARD_CATEGORIES,
    build_arts_directional_validation,
    build_card_crosswalk_sensitivity_summary,
    build_card_external_validation,
    build_validation_crosswalk_table,
)
from preference_analysis.mapping import PREFERENCE_OUTPUT_CATEGORIES  # noqa: E402
from preference_analysis.spatial_demand import (  # noqa: E402
    ABSOLUTE_PROBABILITY_COLUMN,
    CONDITIONAL_SHARE_COLUMN,
    POTENTIAL_DEMAND_COLUMN,
    TARGET_POPULATION_COLUMN,
)


class ExternalValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        gu_rows: list[dict[str, object]] = []
        usage_rows: list[dict[str, object]] = []
        all_card_categories = sorted(
            {
                name
                for names in CARD_VALIDATION_CROSSWALK.values()
                for name in names
            }
        )
        for district_index in range(25):
            district = f"자치구{district_index:02d}"
            weights = (
                np.arange(1, len(PREFERENCE_OUTPUT_CATEGORIES) + 1, dtype=float)
                + district_index / 100
            )
            weights = weights / weights.sum()
            for category, share in zip(
                PREFERENCE_OUTPUT_CATEGORIES, weights, strict=True
            ):
                gu_rows.append(
                    {
                        "자치구코드": f"{district_index:05d}",
                        "시군구": district,
                        "middle_category": category,
                        TARGET_POPULATION_COLUMN: 1000.0,
                        ABSOLUTE_PROBABILITY_COLUMN: share * 0.6,
                        POTENTIAL_DEMAND_COLUMN: share * 600.0,
                        CONDITIONAL_SHARE_COLUMN: share,
                    }
                )
            usage_row: dict[str, object] = {
                "year": 2024,
                "district": district,
            }
            for card_category in all_card_categories:
                usage_row[f"count_{card_category}"] = 0.0
                usage_row[f"amount_{card_category}"] = 0.0
            mapped_count = 0.0
            mapped_amount = 0.0
            for category_index, model_category in enumerate(
                PREFERENCE_OUTPUT_CATEGORIES, start=1
            ):
                first_card_category = CARD_VALIDATION_CROSSWALK[model_category][0]
                usage_row[f"count_{first_card_category}"] += category_index * 10.0
                usage_row[f"amount_{first_card_category}"] += category_index * 1000.0
                mapped_count += category_index * 10.0
                mapped_amount += category_index * 1000.0
            usage_row["transactions"] = mapped_count + 50.0
            usage_row["used_amount_won"] = mapped_amount + 5000.0
            usage_rows.append(usage_row)
        cls.gu = pd.DataFrame(gu_rows)
        cls.usage = pd.DataFrame(usage_rows)

    def test_crosswalk_has_exact_policy_categories(self) -> None:
        crosswalk = build_validation_crosswalk_table()
        self.assertEqual(
            set(crosswalk["model_middle_category"]),
            set(PREFERENCE_OUTPUT_CATEGORIES),
        )
        self.assertEqual(len(crosswalk), len(PREFERENCE_OUTPUT_CATEGORIES))
        self.assertTrue(crosswalk["crosswalk_version"].eq("primary_semantic_v2").all())
        self.assertNotIn("음악", set(crosswalk["model_middle_category"]))
        self.assertIn("음악", EXCLUDED_CARD_CATEGORIES)

    def test_external_validation_outputs_are_complete(self) -> None:
        comparison, district, category, summary = build_card_external_validation(
            self.gu, self.usage, year=2024
        )
        self.assertEqual(len(comparison), 25 * len(PREFERENCE_OUTPUT_CATEGORIES))
        self.assertEqual(len(district), 25)
        self.assertEqual(len(category), len(PREFERENCE_OUTPUT_CATEGORIES))
        self.assertEqual(len(summary), 6)
        conditional_sums = comparison.groupby("시군구")[
            CONDITIONAL_SHARE_COLUMN
        ].sum()
        np.testing.assert_allclose(conditional_sums.to_numpy(), 1.0)
        self.assertTrue(
            comparison["mapped_policy_transaction_coverage"].between(0, 1).all()
        )
        self.assertTrue(
            comparison["mapped_policy_amount_coverage"].between(0, 1).all()
        )
        self.assertTrue(comparison["card_geography_basis"].eq("unverified").all())

    def test_crosswalk_sensitivity_has_three_scenarios(self) -> None:
        summary = build_card_crosswalk_sensitivity_summary(
            self.gu, self.usage, year=2024
        )
        self.assertEqual(len(summary), 3 * 6)
        self.assertEqual(summary["crosswalk_version"].nunique(), 3)

    def test_arts_directional_validation_has_three_by_fourteen_cells(self) -> None:
        probability_rows: list[dict[str, object]] = []
        arts_rows: list[dict[str, object]] = []
        all_arts_columns = sorted(
            {
                column
                for columns in ARTS_ATTENDANCE_COLUMNS.values()
                for column in columns
            }
        )
        for sex_code in (1, 2):
            for age_code in range(1, 8):
                for category in ARTS_ATTENDANCE_COLUMNS:
                    probability_rows.append(
                        {
                            "sex_code": sex_code,
                            "age_code": age_code,
                            "survey_year": 2024,
                            "middle_category": category,
                            ABSOLUTE_PROBABILITY_COLUMN: age_code / 10,
                        }
                    )
                arts_row: dict[str, object] = {
                    "조사년도": 2024,
                    "성별": sex_code,
                    "연령": age_code,
                    "최종가중치": 1.0,
                }
                for column in all_arts_columns:
                    arts_row[column] = float(age_code >= 4)
                arts_rows.append(arts_row)
        cells, summary = build_arts_directional_validation(
            pd.DataFrame(probability_rows),
            pd.DataFrame(arts_rows),
        )
        self.assertEqual(len(cells), 3 * 14)
        self.assertEqual(len(summary), 3)
        self.assertEqual(set(summary["middle_category"]), {"공연", "미술", "영상"})
        self.assertTrue(cells["population_scope"].eq(ARTS_POPULATION_SCOPE).all())
        self.assertTrue(summary["population_scope"].eq(ARTS_POPULATION_SCOPE).all())


if __name__ == "__main__":
    unittest.main()
