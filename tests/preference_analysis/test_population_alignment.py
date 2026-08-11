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

from preference_analysis.population_alignment import (  # noqa: E402
    ALIGNED_POPULATION_COLUMN,
    SOURCE_AGE_ORDER,
    SOURCE_POPULATION_COLUMN,
    align_grid_sex_age_population,
    validate_preference_probability_cells,
)


def synthetic_population() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grid_index, grid_id in enumerate(("다사000000", "다사000001"), start=1):
        for sex in ("남성", "여성"):
            for age_index, age_group in enumerate(SOURCE_AGE_ORDER, start=1):
                rows.append(
                    {
                        "GRID_CD": grid_id,
                        "시군구": "테스트구",
                        "행정동": f"테스트동{grid_index}",
                        "성별": sex,
                        "연령대": age_group,
                        SOURCE_POPULATION_COLUMN: age_index,
                    }
                )
    return pd.DataFrame(rows)


def synthetic_probabilities() -> pd.DataFrame:
    rows = []
    for sex_code in (1, 2):
        for age_code in range(1, 8):
            for category in ("공연", "기타"):
                rows.append(
                    {
                        "sex_code": sex_code,
                        "age_code": age_code,
                        "middle_category": category,
                        "preference_probability": 0.5,
                    }
                )
    return pd.DataFrame(rows)


class PopulationAlignmentTest(unittest.TestCase):
    def test_alignment_preserves_population_and_aggregates_70_plus(self) -> None:
        source = synthetic_population()
        aligned, model_input, summary, validation = align_grid_sex_age_population(
            source
        )

        self.assertEqual(len(aligned), 2 * 2 * 9)
        self.assertEqual(len(model_input), 2 * 2 * 7)
        self.assertEqual(
            int(aligned[ALIGNED_POPULATION_COLUMN].sum()),
            int(source[SOURCE_POPULATION_COLUMN].sum()),
        )
        seventy_plus = aligned.loc[
            aligned["aligned_age_group"].eq("70세 이상")
        ]
        expected_per_grid_sex = sum(range(9, 13))
        self.assertTrue(
            seventy_plus[ALIGNED_POPULATION_COLUMN].eq(expected_per_grid_sex).all()
        )
        self.assertTrue(seventy_plus["model_age_code"].eq(7).all())
        self.assertTrue(seventy_plus["source_age_group_count"].eq(4).all())
        self.assertEqual(
            seventy_plus["source_age_groups"].unique().tolist(),
            ["70-79세|80-89세|90-99세|100세-"],
        )
        self.assertEqual(
            validation.loc[
                validation["metric"].eq("population_conservation_error"),
                "value",
            ].item(),
            0,
        )
        self.assertEqual(summary["aligned_age_group"].nunique(), 9)

    def test_under_15_is_retained_but_not_in_model_input(self) -> None:
        aligned, model_input, _, _ = align_grid_sex_age_population(
            synthetic_population()
        )
        under_15 = aligned["aligned_age_group"].isin(("0-5세", "6-14세"))
        self.assertTrue(aligned.loc[under_15, "model_age_code"].isna().all())
        self.assertFalse(aligned.loc[under_15, "preference_model_applicable"].any())
        self.assertFalse(model_input["aligned_age_group"].isin(("0-5세", "6-14세")).any())

    def test_invalid_age_and_negative_population_are_rejected(self) -> None:
        unknown_age = synthetic_population()
        unknown_age.loc[0, "연령대"] = "알수없음"
        with self.assertRaisesRegex(ValueError, "정의되지 않은 연령대"):
            align_grid_sex_age_population(unknown_age)

        negative = synthetic_population()
        negative.loc[0, SOURCE_POPULATION_COLUMN] = -1
        with self.assertRaisesRegex(ValueError, "음수"):
            align_grid_sex_age_population(negative)

    def test_incomplete_grid_cells_are_rejected(self) -> None:
        incomplete = synthetic_population().iloc[1:].copy()
        with self.assertRaisesRegex(ValueError, "완전하지 않은 격자"):
            align_grid_sex_age_population(incomplete)

    def test_probability_cells_are_complete_and_sum_to_one(self) -> None:
        probabilities = synthetic_probabilities()
        validate_preference_probability_cells(probabilities)

        missing_cell = probabilities.loc[
            ~(
                probabilities["sex_code"].eq(2)
                & probabilities["age_code"].eq(7)
            )
        ]
        with self.assertRaisesRegex(ValueError, "완전하지 않습니다"):
            validate_preference_probability_cells(missing_cell)

        wrong_sum = probabilities.copy()
        wrong_sum.loc[0, "preference_probability"] = 0.4
        with self.assertRaisesRegex(ValueError, "확률 합"):
            validate_preference_probability_cells(wrong_sum)


if __name__ == "__main__":
    unittest.main()
