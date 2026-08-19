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

from preference_analysis.mapping import (  # noqa: E402
    MODEL_CATEGORIES,
    OTHER_CATEGORY,
    PREFERENCE_OUTPUT_CATEGORIES,
)
from preference_analysis.spatial_demand import (  # noqa: E402
    ABSOLUTE_PROBABILITY_COLUMN,
    CONDITIONAL_SHARE_COLUMN,
    OTHER_DEMAND_COLUMN,
    POTENTIAL_DEMAND_COLUMN,
    TARGET_POPULATION_COLUMN,
    build_all_spatial_demand,
    build_grid_preference_demand,
)


def synthetic_probability() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    probability = 1.0 / len(MODEL_CATEGORIES)
    for sex_code in (1, 2):
        for age_code in range(1, 8):
            for category in MODEL_CATEGORIES:
                rows.append(
                    {
                        "sex_code": sex_code,
                        "age_code": age_code,
                        "middle_category": category,
                        "preference_probability_absolute": probability,
                    }
                )
    return pd.DataFrame(rows)


def synthetic_population() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grid, gu, dong, value in (
        ("A", "강남구", "역삼1동", 1.0),
        ("B", "관악구", "신림동", 0.0),
    ):
        for sex_code in (1, 2):
            for age_code in range(1, 8):
                rows.append(
                    {
                        "GRID_CD": grid,
                        "시군구": gu,
                        "행정동": dong,
                        "sex_code": sex_code,
                        "model_age_code": age_code,
                        "preference_model_applicable": True,
                        TARGET_POPULATION_COLUMN: value,
                    }
                )
    return pd.DataFrame(rows)


def synthetic_lookup() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "GRID_CD": "A",
                "행정동코드": 11230640,
                "시군구": "강남구",
                "행정동": "역삼1동",
                "중심점_x": 950050.0,
                "중심점_y": 1949050.0,
            },
            {
                "GRID_CD": "B",
                "행정동코드": 11210680,
                "시군구": "관악구",
                "행정동": "신림동",
                "중심점_x": 951050.0,
                "중심점_y": 1948050.0,
            },
        ]
    )


class SpatialDemandUnitTest(unittest.TestCase):
    def test_formula_and_zero_target_no_data(self) -> None:
        grid = build_grid_preference_demand(
            synthetic_population(),
            synthetic_probability(),
            synthetic_lookup(),
        )
        positive = grid.loc[grid["GRID_CD"].eq("A")]
        self.assertEqual(len(positive), len(PREFERENCE_OUTPUT_CATEGORIES))
        np.testing.assert_allclose(positive[TARGET_POPULATION_COLUMN], 14.0)
        expected_probability = 1.0 / len(MODEL_CATEGORIES)
        expected_demand = 14.0 * expected_probability
        np.testing.assert_allclose(
            positive[ABSOLUTE_PROBABILITY_COLUMN], expected_probability
        )
        np.testing.assert_allclose(positive[POTENTIAL_DEMAND_COLUMN], expected_demand)
        np.testing.assert_allclose(positive[OTHER_DEMAND_COLUMN], expected_demand)
        np.testing.assert_allclose(
            positive[CONDITIONAL_SHARE_COLUMN],
            1 / len(PREFERENCE_OUTPUT_CATEGORIES),
        )

        no_data = grid.loc[grid["GRID_CD"].eq("B")]
        self.assertTrue(no_data[ABSOLUTE_PROBABILITY_COLUMN].isna().all())
        self.assertTrue(no_data[CONDITIONAL_SHARE_COLUMN].isna().all())
        self.assertAlmostEqual(float(no_data[POTENTIAL_DEMAND_COLUMN].sum()), 0.0)

    def test_grid_to_dong_to_gu_conservation(self) -> None:
        grid, dong, gu, validation = build_all_spatial_demand(
            synthetic_population(),
            synthetic_probability(),
            synthetic_lookup(),
        )
        self.assertFalse(validation["status"].eq("fail").any())
        grid_target = grid.drop_duplicates("GRID_CD")[TARGET_POPULATION_COLUMN].sum()
        dong_target = dong.drop_duplicates("행정동코드")[TARGET_POPULATION_COLUMN].sum()
        gu_target = gu.drop_duplicates("자치구코드")[TARGET_POPULATION_COLUMN].sum()
        self.assertAlmostEqual(float(grid_target), float(dong_target))
        self.assertAlmostEqual(float(grid_target), float(gu_target))

    def test_duplicate_population_key_is_rejected(self) -> None:
        population = synthetic_population()
        population = pd.concat([population, population.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "고유하지 않습니다"):
            build_grid_preference_demand(
                population,
                synthetic_probability(),
                synthetic_lookup(),
            )

    def test_negative_population_is_rejected(self) -> None:
        population = synthetic_population()
        population.loc[0, TARGET_POPULATION_COLUMN] = -1
        with self.assertRaisesRegex(ValueError, "음수가 있습니다"):
            build_grid_preference_demand(
                population,
                synthetic_probability(),
                synthetic_lookup(),
            )

    def test_probability_requires_other_class(self) -> None:
        probability = synthetic_probability().loc[
            lambda frame: frame["middle_category"].ne(OTHER_CATEGORY)
        ]
        with self.assertRaisesRegex(
            ValueError, f"{len(MODEL_CATEGORIES)}개 클래스"
        ):
            build_grid_preference_demand(
                synthetic_population(),
                probability,
                synthetic_lookup(),
            )


class RealSpatialInputSmokeTest(unittest.TestCase):
    def test_current_inputs_have_expected_complete_geography(self) -> None:
        population_path = (
            PROJECT_ROOT
            / "data/processed/preference_analysis/population/"
            "grid_sex_age_target_population_model_input_2024.csv"
        )
        probability_path = (
            PROJECT_ROOT
            / "data/processed/preference_analysis/model/"
            "sex_age_middle_category_preference_2024.csv"
        )
        lookup_path = PROJECT_ROOT / "data/raw/spatial/grid_pop_access.csv"
        if not (population_path.exists() and probability_path.exists() and lookup_path.exists()):
            self.skipTest("로컬 대용량 공간 입력이 없어 실데이터 smoke test를 건너뜁니다.")
        population = pd.read_csv(population_path, encoding="utf-8-sig", low_memory=False)
        probability = pd.read_csv(probability_path, encoding="utf-8-sig")
        lookup = pd.read_csv(lookup_path, encoding="utf-8-sig", low_memory=False)
        grid = build_grid_preference_demand(population, probability, lookup)
        self.assertEqual(grid["GRID_CD"].nunique(), 60_528)
        self.assertEqual(grid["행정동코드"].nunique(), 426)
        self.assertEqual(grid["시군구"].nunique(), 25)
        self.assertEqual(
            len(grid), 60_528 * len(PREFERENCE_OUTPUT_CATEGORIES)
        )


if __name__ == "__main__":
    unittest.main()
