from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely import box


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) in sys.path:
    sys.path.remove(str(SRC_PATH))
sys.path.insert(0, str(SRC_PATH))

from preference_analysis.interactive_maps import (  # noqa: E402
    _quantile_thresholds,
    build_grid_feature_collection,
    write_interactive_dong_map,
    write_interactive_grid_map,
)
from preference_analysis.mapping import PREFERENCE_OUTPUT_CATEGORIES  # noqa: E402
from preference_analysis.spatial_demand import (  # noqa: E402
    POTENTIAL_DEMAND_COLUMN,
    build_all_spatial_demand,
)
from test_spatial_demand import (  # noqa: E402
    synthetic_lookup,
    synthetic_population,
    synthetic_probability,
)


class InteractiveMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid, cls.dong, _, _ = build_all_spatial_demand(
            synthetic_population(),
            synthetic_probability(),
            synthetic_lookup(),
        )

    def test_grid_feature_collection_keeps_zero_target_grid(self) -> None:
        features = build_grid_feature_collection(self.grid)
        self.assertEqual(len(features["features"]), 2)
        by_id = {feature["properties"]["g"]: feature for feature in features["features"]}
        self.assertEqual(by_id["B"]["properties"]["t"], 0.0)
        self.assertTrue(all(value is None for value in by_id["B"]["properties"]["pa"]))

    def test_map_quantiles_exclude_zero_target_no_data_grids(self) -> None:
        thresholds = _quantile_thresholds(
            self.grid,
            value_column=POTENTIAL_DEMAND_COLUMN,
        )
        for category in PREFERENCE_OUTPUT_CATEGORIES:
            self.assertTrue(all(value > 0 for value in thresholds[category]))

    def test_html_maps_contain_korean_controls_and_all_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            grid_html = temporary / "grid.html"
            write_interactive_grid_map(self.grid, grid_html)
            grid_text = grid_html.read_text(encoding="utf-8")
            self.assertIn('id="category-select"', grid_text)
            self.assertIn('id="metric-select"', grid_text)
            self.assertIn("무자료는 0%가 아닙니다", grid_text)
            self.assertNotIn('"음악"', grid_text)
            for category in PREFERENCE_OUTPUT_CATEGORIES:
                self.assertIn(category, grid_text)

            boundary = gpd.GeoDataFrame(
                {
                    "ADM_CD": ["11230640", "11210680"],
                    "ADM_NM": ["역삼1동", "신림동"],
                },
                geometry=[
                    box(126.9, 37.4, 127.0, 37.5),
                    box(127.0, 37.4, 127.1, 37.5),
                ],
                crs="EPSG:4326",
            )
            boundary_path = temporary / "dong.geojson"
            boundary.to_file(boundary_path, driver="GeoJSON")
            dong_html = temporary / "dong.html"
            write_interactive_dong_map(self.dong, boundary_path, dong_html)
            dong_text = dong_html.read_text(encoding="utf-8")
            self.assertIn("서울시 행정동별", dong_text)
            self.assertIn("행정동 값은 100m 격자 추정치를", dong_text)
            self.assertIn("역삼1동", dong_text)
            self.assertIn("신림동", dong_text)
            self.assertNotIn('"음악"', dong_text)


if __name__ == "__main__":
    unittest.main()
