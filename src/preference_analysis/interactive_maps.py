"""Generate static, interactive Leaflet maps from saved preference estimates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import box, set_precision

from .mapping import PREFERENCE_OUTPUT_CATEGORIES
from .spatial_demand import (
    ABSOLUTE_PROBABILITY_COLUMN,
    CONDITIONAL_SHARE_COLUMN,
    OTHER_PROBABILITY_COLUMN,
    POTENTIAL_DEMAND_COLUMN,
    TARGET_POPULATION_COLUMN,
)


GRID_SOURCE_CRS = "EPSG:5179"
MAP_CRS = "EPSG:4326"
NO_DATA_COLOR = "#d9d9d9"
PROBABILITY_PALETTE = (
    "#eff3ff",
    "#c6dbef",
    "#9ecae1",
    "#6baed6",
    "#4292c6",
    "#2171b5",
    "#084594",
)
DEMAND_PALETTE = (
    "#ffffcc",
    "#ffeda0",
    "#fed976",
    "#feb24c",
    "#fd8d3c",
    "#f03b20",
    "#bd0026",
)


def _compact_number(value: float | int | None, digits: int = 8) -> float | None:
    if value is None or not np.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _metric_arrays(
    demand: pd.DataFrame,
    *,
    region_key: str,
) -> pd.DataFrame:
    categories = list(PREFERENCE_OUTPUT_CATEGORIES)
    base_columns = [
        region_key,
        TARGET_POPULATION_COLUMN,
        OTHER_PROBABILITY_COLUMN,
    ]
    base = demand[base_columns].drop_duplicates(region_key).set_index(region_key)
    pivots: dict[str, pd.DataFrame] = {}
    for metric in (
        ABSOLUTE_PROBABILITY_COLUMN,
        POTENTIAL_DEMAND_COLUMN,
        CONDITIONAL_SHARE_COLUMN,
    ):
        pivots[metric] = demand.pivot(
            index=region_key,
            columns="middle_category",
            values=metric,
        ).reindex(columns=categories)
    output = base.copy()
    output["absolute_values"] = [
        [_compact_number(value) for value in row]
        for row in pivots[ABSOLUTE_PROBABILITY_COLUMN].to_numpy(dtype=float)
    ]
    output["demand_values"] = [
        [_compact_number(value, digits=6) for value in row]
        for row in pivots[POTENTIAL_DEMAND_COLUMN].to_numpy(dtype=float)
    ]
    output["conditional_values"] = [
        [_compact_number(value) for value in row]
        for row in pivots[CONDITIONAL_SHARE_COLUMN].to_numpy(dtype=float)
    ]
    return output.reset_index()


def _quantile_thresholds(
    metric_frame: pd.DataFrame,
    *,
    value_column: str,
) -> dict[str, list[float]]:
    if TARGET_POPULATION_COLUMN not in metric_frame.columns:
        raise ValueError(
            f"지도 분위 계산에 {TARGET_POPULATION_COLUMN} 열이 필요합니다."
        )
    positive_target = pd.to_numeric(
        metric_frame[TARGET_POPULATION_COLUMN], errors="coerce"
    ).gt(0)
    thresholds: dict[str, list[float]] = {}
    for category in PREFERENCE_OUTPUT_CATEGORIES:
        values = pd.to_numeric(
            metric_frame.loc[
                positive_target & metric_frame["middle_category"].eq(category),
                value_column,
            ],
            errors="coerce",
        ).to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if len(values) == 0:
            thresholds[category] = [0.0] * 6
            continue
        quantiles = np.quantile(values, np.arange(1, 7) / 7)
        thresholds[category] = [round(float(value), 10) for value in quantiles]
    return thresholds


def build_grid_feature_collection(
    grid_demand: pd.DataFrame,
    *,
    seoul_boundary_path: Path | None = None,
) -> dict[str, Any]:
    """Reconstruct exact 100m cells from EPSG:5179 centers for map display."""

    arrays = _metric_arrays(grid_demand, region_key="GRID_CD")
    base = grid_demand[
        [
            "GRID_CD",
            "행정동코드",
            "시군구",
            "행정동",
            "중심점_x",
            "중심점_y",
        ]
    ].drop_duplicates("GRID_CD")
    mapped = base.merge(arrays, on="GRID_CD", how="left", validate="one_to_one")
    geometry = [
        box(float(x) - 50.0, float(y) - 50.0, float(x) + 50.0, float(y) + 50.0)
        for x, y in zip(mapped["중심점_x"], mapped["중심점_y"], strict=True)
    ]
    geo = gpd.GeoDataFrame(mapped, geometry=geometry, crs=GRID_SOURCE_CRS)
    if seoul_boundary_path is not None:
        boundary = gpd.read_file(seoul_boundary_path).to_crs(GRID_SOURCE_CRS)
        seoul_outline = boundary.geometry.union_all()
        geo.geometry = geo.geometry.intersection(seoul_outline)
        geo = geo.loc[~geo.geometry.is_empty].copy()
    geo = geo.to_crs(MAP_CRS)
    geo.geometry = set_precision(geo.geometry, grid_size=1e-6)

    features: list[dict[str, Any]] = []
    for row in geo.itertuples(index=False):
        geometry_mapping = row.geometry.__geo_interface__
        properties = {
            "g": str(row.GRID_CD),
            "dc": str(row.행정동코드).zfill(8),
            "gu": str(row.시군구),
            "dn": str(row.행정동),
            "t": _compact_number(row.target_population_est, digits=6),
            "pa": row.absolute_values,
            "pd": row.demand_values,
            "pc": row.conditional_values,
            "op": _compact_number(row.other_probability_absolute),
        }
        features.append(
            {"type": "Feature", "properties": properties, "geometry": geometry_mapping}
        )
    return {"type": "FeatureCollection", "features": features}


def build_dong_feature_collection(
    dong_demand: pd.DataFrame,
    boundary_path: Path,
) -> dict[str, Any]:
    """Join 2024 estimates to display-only administrative-dong polygons by code."""

    arrays = _metric_arrays(dong_demand, region_key="행정동코드")
    labels = dong_demand[
        ["행정동코드", "시군구", "행정동"]
    ].drop_duplicates("행정동코드")
    values = labels.merge(arrays, on="행정동코드", how="left", validate="one_to_one")
    values["행정동코드"] = values["행정동코드"].astype("string").str.zfill(8)

    boundary = gpd.read_file(boundary_path).to_crs(MAP_CRS)
    boundary["행정동코드"] = boundary["ADM_CD"].astype("string").str.zfill(8)
    geo = boundary[["행정동코드", "geometry"]].merge(
        values,
        on="행정동코드",
        how="left",
        validate="one_to_one",
    )
    if geo[TARGET_POPULATION_COLUMN].isna().any():
        missing = geo.loc[
            geo[TARGET_POPULATION_COLUMN].isna(), "행정동코드"
        ].tolist()
        raise ValueError(f"행정동 경계에 잠재수요가 결합되지 않은 코드가 있습니다: {missing}")
    geo.geometry = set_precision(geo.geometry, grid_size=1e-6)

    features: list[dict[str, Any]] = []
    for row in geo.itertuples(index=False):
        properties = {
            "g": str(row.행정동코드),
            "dc": str(row.행정동코드),
            "gu": str(row.시군구),
            "dn": str(row.행정동),
            "t": _compact_number(row.target_population_est, digits=6),
            "pa": row.absolute_values,
            "pd": row.demand_values,
            "pc": row.conditional_values,
            "op": _compact_number(row.other_probability_absolute),
        }
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": row.geometry.__geo_interface__,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _map_html(
    feature_collection: dict[str, Any],
    *,
    title: str,
    unit_label: str,
    notice: str,
    thresholds: dict[str, dict[str, list[float]]],
    default_category: str = "관광지",
    default_metric: str = "potential_demand_absolute",
) -> str:
    categories_json = json.dumps(
        list(PREFERENCE_OUTPUT_CATEGORIES), ensure_ascii=False, separators=(",", ":")
    )
    data_json = json.dumps(
        feature_collection,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    thresholds_json = json.dumps(
        thresholds, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    probability_palette = json.dumps(PROBABILITY_PALETTE)
    demand_palette = json.dumps(DEMAND_PALETTE)
    safe_title = json.dumps(title, ensure_ascii=False)
    safe_unit = json.dumps(unit_label, ensure_ascii=False)
    safe_notice = json.dumps(notice, ensure_ascii=False)
    safe_default_category = json.dumps(default_category, ensure_ascii=False)
    safe_default_metric = json.dumps(default_metric)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body {{ height: 100%; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif; }}
    body {{ display: flex; flex-direction: column; background: #f7f7f7; color: #1f2937; }}
    .toolbar {{ display: flex; gap: 12px; align-items: end; flex-wrap: wrap; padding: 10px 14px; background: #ffffff; border-bottom: 1px solid #d1d5db; z-index: 1000; }}
    .title {{ font-weight: 750; font-size: 17px; margin-right: auto; }}
    label {{ display: grid; gap: 3px; font-size: 12px; color: #4b5563; }}
    select {{ min-width: 150px; padding: 7px 28px 7px 9px; border: 1px solid #9ca3af; border-radius: 6px; background: white; font: inherit; color: #111827; }}
    #map {{ flex: 1; min-height: 540px; }}
    .notice {{ padding: 6px 14px; background: #fff7ed; border-top: 1px solid #fed7aa; font-size: 12px; color: #7c2d12; }}
    .legend {{ background: rgba(255,255,255,.96); padding: 8px 10px; border: 1px solid #9ca3af; border-radius: 5px; box-shadow: 0 1px 4px rgba(0,0,0,.15); line-height: 18px; font-size: 11px; }}
    .legend-row {{ display: flex; align-items: center; gap: 6px; white-space: nowrap; }}
    .legend-swatch {{ width: 17px; height: 11px; border: 1px solid rgba(0,0,0,.22); }}
    .popup-title {{ font-weight: 750; font-size: 14px; margin-bottom: 5px; }}
    .popup-grid {{ display: grid; grid-template-columns: auto auto; gap: 2px 12px; }}
    .popup-note {{ margin-top: 6px; color: #92400e; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="toolbar">
    <div class="title" id="map-title"></div>
    <label>정책 분야<select id="category-select"></select></label>
    <label>표시 지표<select id="metric-select">
      <option value="potential_demand_absolute">절대 잠재수요</option>
      <option value="preference_probability_absolute">절대 선호확률</option>
    </select></label>
  </div>
  <div id="map" role="application" aria-label="서울시 선호예측 지도"></div>
  <div class="notice" id="map-notice"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
  (() => {{
    const title = {safe_title};
    const unitLabel = {safe_unit};
    const notice = {safe_notice};
    const categories = {categories_json};
    const featureData = {data_json};
    const thresholds = {thresholds_json};
    const palettes = {{
      preference_probability_absolute: {probability_palette},
      potential_demand_absolute: {demand_palette}
    }};
    const state = {{ category: {safe_default_category}, metric: {safe_default_metric} }};
    const categorySelect = document.getElementById('category-select');
    const metricSelect = document.getElementById('metric-select');
    const titleElement = document.getElementById('map-title');
    titleElement.textContent = title;
    document.getElementById('map-notice').textContent = notice;
    categories.forEach(category => {{
      const option = document.createElement('option');
      option.value = category; option.textContent = category;
      categorySelect.appendChild(option);
    }});
    categorySelect.value = state.category;
    metricSelect.value = state.metric;

    const map = L.map('map', {{ preferCanvas: true, zoomControl: true, minZoom: 9 }});
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);
    const renderer = L.canvas({{ padding: 0.35, tolerance: 4 }});
    const metricIndex = {{
      preference_probability_absolute: 'pa',
      potential_demand_absolute: 'pd'
    }};
    const categoryIndex = () => categories.indexOf(state.category);
    const metricValue = properties => {{
      if (!(properties.t > 0)) return null;
      const values = properties[metricIndex[state.metric]];
      const value = values ? values[categoryIndex()] : null;
      return Number.isFinite(value) ? value : null;
    }};
    const binIndex = value => {{
      const cuts = thresholds[state.metric][state.category];
      let index = 0;
      while (index < cuts.length && value > cuts[index]) index += 1;
      return index;
    }};
    const styleFeature = feature => {{
      const value = metricValue(feature.properties);
      if (value === null) return {{
        color: '#9ca3af', weight: 0.25, fillColor: '{NO_DATA_COLOR}',
        fillOpacity: 0.22, opacity: 0.5
      }};
      return {{
        color: '#6b7280', weight: unitLabel === '100m 격자' ? 0.18 : 0.7,
        fillColor: palettes[state.metric][binIndex(value)],
        fillOpacity: unitLabel === '100m 격자' ? 0.78 : 0.72,
        opacity: 0.65
      }};
    }};
    const escapeHtml = value => String(value).replace(/[&<>'"]/g, char => ({{
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }}[char]));
    const fmt = (value, digits=2) => Number.isFinite(value)
      ? Number(value).toLocaleString('ko-KR', {{ maximumFractionDigits: digits }})
      : '무자료';
    const popupHtml = properties => {{
      const index = categoryIndex();
      const absolute = properties.pa?.[index];
      const demand = properties.pd?.[index];
      const conditional = properties.pc?.[index];
      const noData = !(properties.t > 0);
      return `<div class="popup-title">${{escapeHtml(properties.gu)}} ${{escapeHtml(properties.dn)}}</div>
        <div class="popup-grid">
          <span>${{escapeHtml(unitLabel)}} ID</span><b>${{escapeHtml(properties.g)}}</b>
          <span>정책 분야</span><b>${{escapeHtml(state.category)}}</b>
          <span>15세 이상 추정 대상자</span><b>${{fmt(properties.t)}}명</b>
          <span>절대 선호확률</span><b>${{Number.isFinite(absolute) ? fmt(absolute * 100) + '%' : '무자료'}}</b>
          <span>절대 잠재수요</span><b>${{Number.isFinite(demand) ? fmt(demand) + '명' : '무자료'}}</b>
          <span>9개 분야 내 구성비</span><b>${{Number.isFinite(conditional) ? fmt(conditional * 100) + '%' : '무자료'}}</b>
          <span>기타 절대확률</span><b>${{Number.isFinite(properties.op) ? fmt(properties.op * 100) + '%' : '무자료'}}</b>
        </div>
        <div class="popup-note">${{noData ? '15세 이상 추정 대상자가 0명인 무자료 영역입니다.' : '모든 값은 2024년 기준 추정치입니다.'}}</div>`;
    }};
    const layer = L.geoJSON(featureData, {{
      renderer,
      style: styleFeature,
      onEachFeature: (feature, polygon) => {{
        polygon.on('click', () => polygon.bindPopup(popupHtml(feature.properties), {{ maxWidth: 350 }}).openPopup());
      }}
    }}).addTo(map);
    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, {{ padding: [8, 8] }});

    const legend = L.control({{ position: 'bottomright' }});
    legend.onAdd = () => {{
      const div = L.DomUtil.create('div', 'legend');
      div.id = 'dynamic-legend';
      L.DomEvent.disableClickPropagation(div);
      return div;
    }};
    legend.addTo(map);
    const formatLegend = value => {{
      if (state.metric === 'preference_probability_absolute') {{
        return `${{Number(value * 100).toLocaleString('ko-KR', {{ maximumFractionDigits: 2 }})}}%`;
      }}
      return `${{Number(value).toLocaleString('ko-KR', {{ maximumSignificantDigits: 3 }})}}명`;
    }};
    const updateLegend = () => {{
      const div = document.getElementById('dynamic-legend');
      const cuts = thresholds[state.metric][state.category];
      const palette = palettes[state.metric];
      const metricLabel = state.metric === 'preference_probability_absolute' ? '절대 선호확률' : '절대 잠재수요';
      const rows = palette.map((color, index) => {{
        const lower = index === 0 ? null : cuts[index - 1];
        const upper = index === cuts.length ? null : cuts[index];
        const label = lower === null ? `≤ ${{formatLegend(upper)}}`
          : upper === null ? `> ${{formatLegend(lower)}}`
          : `${{formatLegend(lower)}} ~ ${{formatLegend(upper)}}`;
        return `<div class="legend-row"><span class="legend-swatch" style="background:${{color}}"></span>${{label}}</div>`;
      }}).join('');
      div.innerHTML = `<b>${{state.category}} · ${{metricLabel}}</b>${{rows}}<div class="legend-row"><span class="legend-swatch" style="background:{NO_DATA_COLOR}"></span>무자료</div><small>분야별 분위 기준</small>`;
    }};
    const update = () => {{
      map.closePopup();
      layer.setStyle(styleFeature);
      updateLegend();
    }};
    categorySelect.addEventListener('change', event => {{ state.category = event.target.value; update(); }});
    metricSelect.addEventListener('change', event => {{ state.metric = event.target.value; update(); }});
    updateLegend();
  }})();
  </script>
</body>
</html>"""


def write_interactive_grid_map(
    grid_demand: pd.DataFrame,
    output_path: Path,
    *,
    seoul_boundary_path: Path | None = None,
) -> Path:
    """Write a single-layer dynamic 100m map; opening it never retrains a model."""

    features = build_grid_feature_collection(
        grid_demand, seoul_boundary_path=seoul_boundary_path
    )
    thresholds = {
        ABSOLUTE_PROBABILITY_COLUMN: _quantile_thresholds(
            grid_demand, value_column=ABSOLUTE_PROBABILITY_COLUMN
        ),
        POTENTIAL_DEMAND_COLUMN: _quantile_thresholds(
            grid_demand, value_column=POTENTIAL_DEMAND_COLUMN
        ),
    }
    html = _map_html(
        features,
        title="서울시 100m 격자 만족활동 기반 선호·잠재수요",
        unit_label="100m 격자",
        notice=(
            "100m 결과는 관측값이 아닌 추정치이며 작은 격자일수록 "
            "불확실성이 큽니다. 정책 해석에는 행정동 결과를 함께 사용하세요. "
            "무자료는 0%가 아닙니다."
        ),
        thresholds=thresholds,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def write_interactive_dong_map(
    dong_demand: pd.DataFrame,
    boundary_path: Path,
    output_path: Path,
) -> Path:
    """Write a dynamic administrative-dong choropleth joined strictly by code."""

    features = build_dong_feature_collection(dong_demand, boundary_path)
    thresholds = {
        ABSOLUTE_PROBABILITY_COLUMN: _quantile_thresholds(
            dong_demand, value_column=ABSOLUTE_PROBABILITY_COLUMN
        ),
        POTENTIAL_DEMAND_COLUMN: _quantile_thresholds(
            dong_demand, value_column=POTENTIAL_DEMAND_COLUMN
        ),
    }
    html = _map_html(
        features,
        title="서울시 행정동별 만족활동 기반 선호·잠재수요",
        unit_label="행정동",
        notice=(
            "행정동 값은 100m 격자 추정치를 대상자 수로 가중 집계한 2024년 "
            "추정치입니다. 경계는 2025년 표시용 자료이며 무자료는 0%가 아닙니다."
        ),
        thresholds=thresholds,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
