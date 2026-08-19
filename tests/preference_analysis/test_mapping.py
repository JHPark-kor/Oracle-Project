from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) in sys.path:
    sys.path.remove(str(SRC_PATH))
sys.path.insert(0, str(SRC_PATH))

from preference_analysis.mapping import (  # noqa: E402
    FUTURE_PREFERENCE_COLUMNS,
    MODEL_CATEGORIES,
    OTHER_CATEGORY,
    POLICY_EXCLUDED_PREFERENCE_CATEGORIES,
    PREFERENCE_OUTPUT_CATEGORIES,
    SATISFACTION_RANK_COLUMNS,
    UNMODELED_PREFERENCE_CATEGORIES,
    build_activity_mapping,
    transform_satisfaction_ranks,
)


class MappingSpecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PROJECT_ROOT / "data/raw/surveys/leisure_2021_2025.csv"
        cls.mapping = build_activity_mapping(cls.source)

    def test_mapping_covers_exactly_1_to_88(self) -> None:
        self.assertEqual(self.mapping["activity_code"].tolist(), list(range(1, 89)))
        self.assertFalse(self.mapping["activity_code"].duplicated().any())
        self.assertFalse(self.mapping["activity_name_original"].isna().any())

    def test_model_categories_are_expected(self) -> None:
        self.assertEqual(
            set(self.mapping["model_middle_category"].unique()), set(MODEL_CATEGORIES)
        )
        for code in (35, 42, 48):
            actual = self.mapping.loc[
                self.mapping["activity_code"].eq(code), "model_middle_category"
            ].item()
            self.assertEqual(actual, OTHER_CATEGORY)

    def test_sports_goods_is_not_a_preference_output_category(self) -> None:
        self.assertNotIn("체육용품", PREFERENCE_OUTPUT_CATEGORIES)
        self.assertEqual(UNMODELED_PREFERENCE_CATEGORIES, {"체육용품"})
        sports_goods = self.mapping.loc[self.mapping["activity_code"].eq(35)].iloc[0]
        self.assertEqual(sports_goods["legacy_middle_category"], "체육용품")
        self.assertEqual(sports_goods["model_middle_category"], OTHER_CATEGORY)
        self.assertEqual(
            sports_goods["preference_model_status"],
            "미산출(직접 선호라벨 부족)",
        )
        self.assertFalse(bool(sports_goods["include_in_policy_category"]))

    def test_music_is_preserved_for_audit_but_routed_to_other(self) -> None:
        self.assertEqual(len(PREFERENCE_OUTPUT_CATEGORIES), 8)
        self.assertNotIn("음악", PREFERENCE_OUTPUT_CATEGORIES)
        self.assertEqual(POLICY_EXCLUDED_PREFERENCE_CATEGORIES, {"음악"})
        music = self.mapping.loc[self.mapping["activity_code"].isin((76, 77))]
        self.assertEqual(set(music["legacy_middle_category"]), {"음악"})
        self.assertEqual(set(music["model_middle_category"]), {OTHER_CATEGORY})
        self.assertEqual(
            set(music["preference_model_status"]),
            {"정책범위 제외(기타 선택지로 통합)"},
        )
        self.assertFalse(music["include_in_policy_category"].astype(bool).any())

    def test_original_sports_category_label_is_preserved(self) -> None:
        sports = self.mapping.loc[self.mapping["activity_code"].isin((16, 18, 19))]
        self.assertEqual(set(sports["legacy_middle_category"]), {"스포츠 관람"})
        self.assertEqual(set(sports["model_middle_category"]), {"스포츠관람"})

    def test_source_activity_names_are_preserved_verbatim(self) -> None:
        reconstructed = (
            "한 번 이상 참여한 여가활동 - ("
            + self.mapping["activity_code"].astype(str)
            + ") "
            + self.mapping["activity_name_original"]
        )
        self.assertTrue(reconstructed.equals(self.mapping["source_column_original"]))


class SatisfactionTransformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PROJECT_ROOT / "data/raw/surveys/leisure_2021_2025.csv"
        cls.mapping = build_activity_mapping(cls.source)
        cls.output, cls.validation, cls.distribution = transform_satisfaction_ranks(
            cls.source, cls.mapping
        )

    def test_full_dataset_has_no_failed_validation(self) -> None:
        self.assertFalse(self.validation["status"].eq("fail").any())
        self.assertEqual(len(self.output), 50_238)

    def test_future_preference_columns_are_excluded(self) -> None:
        self.assertTrue(set(FUTURE_PREFERENCE_COLUMNS).isdisjoint(self.output.columns))

    def test_every_non_missing_satisfaction_code_is_mapped(self) -> None:
        for rank, column in enumerate(SATISFACTION_RANK_COLUMNS, start=1):
            valid = self.output[column].notna()
            self.assertTrue(
                self.output.loc[valid, f"만족활동_{rank}순위_원본활동명"].notna().all()
            )
            self.assertTrue(
                self.output.loc[valid, f"만족활동_{rank}순위_중분류"].notna().all()
            )

    def test_original_rank_codes_round_trip(self) -> None:
        raw = pd.read_csv(
            self.source,
            usecols=list(SATISFACTION_RANK_COLUMNS),
            dtype={column: "string" for column in SATISFACTION_RANK_COLUMNS},
            encoding="utf-8-sig",
        )
        for column in SATISFACTION_RANK_COLUMNS:
            expected = pd.to_numeric(raw[column], errors="coerce").astype("Int64")
            actual = self.output[column]
            self.assertTrue(expected.equals(actual))

    def test_missing_rank_values_are_preserved(self) -> None:
        expected_missing = [0, 237, 904]
        actual_missing = [
            int(self.output[column].isna().sum()) for column in SATISFACTION_RANK_COLUMNS
        ]
        self.assertEqual(actual_missing, expected_missing)

    def test_repeated_original_codes_are_reported_but_not_rejected(self) -> None:
        row = self.validation.loc[
            self.validation["check"].eq(
                "repeated_original_activity_code_across_ranks"
            )
        ].iloc[0]
        self.assertEqual(row["status"], "warning")
        self.assertEqual(int(row["value"]), 2)


if __name__ == "__main__":
    unittest.main()
