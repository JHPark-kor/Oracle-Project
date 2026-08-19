from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from shapely.geometry import box
from sklearn.cluster import DBSCAN


PROJECT_PATH = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = PROJECT_PATH / "notebooks" / "dashboard"
ACCESS_PATH = PROJECT_PATH / "notebooks" / "access" / "OUTPUT" / "h3sfca"

INPUT_PATH = ACCESS_PATH / "h3sfca_격자_중분류_접근성.csv"
OUTPUT_PATH = DASHBOARD_PATH / "OUTPUT" / "vulnerability_index" / "h3sfca_category_dbscan"
IMAGE_PATH = DASHBOARD_PATH / "IMAGE" / "vulnerability_index" / "h3sfca_category_dbscan"

TARGET_POP_COL = "문화누리대상자_추정_인구수"
ACCESS_COL = "접근성지수"
X_COL = "중심점_x"
Y_COL = "중심점_y"

GRID_SIZE_M = 100
GRID_AREA_M2 = GRID_SIZE_M * GRID_SIZE_M
VULNERABLE_QUANTILE = 0.10
DBSCAN_EPS_M = 150
DBSCAN_MIN_SAMPLES = 4

CATEGORY_ORDER = [
    "공연",
    "관광지",
    "도서",
    "문화체험",
    "미술",
    "스포츠관람",
    "영상",
    "음악",
    "체육시설",
    "체육용품",
]

CATEGORY_SLUG = {
    "공연": "performance",
    "관광지": "tourism",
    "도서": "book",
    "문화체험": "culture-experience",
    "미술": "art",
    "스포츠관람": "sports-watch",
    "영상": "video",
    "음악": "music",
    "체육시설": "sports-facility",
    "체육용품": "sports-goods",
}

STYLE = {
    "background": "#FBF6EF",
    "text": "#2A211D",
    "axis": "#D8D2CA",
    "boundary": "#6C645D",
    "cluster_boundary": "#5A261E",
    "muted": "#766F67",
}

VULNERABILITY_CMAP = LinearSegmentedColormap.from_list(
    "h3sfca_category_vulnerability",
    ["#F8E7DC", "#F3C38C", "#F46B2F", "#B84A34", "#6F231B"],
)
VULNERABILITY_NORM = Normalize(vmin=90, vmax=100)


def configure_font() -> tuple[fm.FontProperties | None, fm.FontProperties | None]:
    static_font_dir = PROJECT_PATH / "analysis_table" / "image" / "_fonts"
    medium_path = static_font_dir / "NotoSansKR-Medium.ttf"
    bold_path = static_font_dir / "NotoSansKR-Bold.ttf"
    windows_noto = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf")

    body_font = None
    title_font = None

    if medium_path.exists():
        fm.fontManager.addfont(str(medium_path))
        body_font = fm.FontProperties(fname=str(medium_path))
        plt.rcParams["font.family"] = body_font.get_name()
    elif windows_noto.exists():
        fm.fontManager.addfont(str(windows_noto))
        plt.rcParams["font.family"] = "Noto Sans KR"
        body_font = fm.FontProperties(family="Noto Sans KR", weight="medium")
    else:
        plt.rcParams["font.family"] = "Malgun Gothic"

    if bold_path.exists():
        fm.fontManager.addfont(str(bold_path))
        title_font = fm.FontProperties(fname=str(bold_path))
    elif windows_noto.exists():
        title_font = fm.FontProperties(family="Noto Sans KR", weight="bold")

    plt.rcParams.update(
        {
            "axes.unicode_minus": False,
            "figure.facecolor": STYLE["background"],
            "axes.facecolor": STYLE["background"],
            "savefig.facecolor": STYLE["background"],
            "text.color": STYLE["text"],
        }
    )
    return body_font, title_font


BODY_FONT, TITLE_FONT = configure_font()
TITLE_KWARGS = {"fontproperties": TITLE_FONT} if TITLE_FONT is not None else {"fontweight": "bold"}


def vulnerability_score_from_low_access(series: pd.Series) -> pd.Series:
    rank = series.rank(method="min", ascending=True)
    n = len(series)
    if n <= 1:
        return pd.Series(100.0, index=series.index)
    score = 100 * (1 - (rank - 1) / (n - 1))
    return score.clip(0, 100)


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if valid.any():
        return float(np.average(values.loc[valid], weights=weights.loc[valid]))
    return float(values.mean())


def top_value(series: pd.Series) -> str | None:
    values = series.dropna()
    if values.empty:
        return None
    return str(values.mode().iloc[0])


def load_h3sfca_access() -> pd.DataFrame:
    usecols = [
        "GRID_CD",
        "시군구",
        "행정동",
        X_COL,
        Y_COL,
        "추정_인구수",
        TARGET_POP_COL,
        "중분류",
        ACCESS_COL,
        "접근가능_가맹점수",
        "평균접근비용",
        "선호수요",
        "수요량",
    ]
    data = pd.read_csv(INPUT_PATH, usecols=usecols)
    data = data[
        data[TARGET_POP_COL].gt(0)
        & data[ACCESS_COL].notna()
        & data[[X_COL, Y_COL]].notna().all(axis=1)
    ].copy()
    data["중분류"] = pd.Categorical(data["중분류"], categories=CATEGORY_ORDER, ordered=True)
    return data.sort_values(["중분류", "GRID_CD"]).reset_index(drop=True)


def run_category_dbscan(access: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    vulnerable_rows = []
    cluster_rows = []
    summary_rows = []

    for category_idx, category in enumerate(CATEGORY_ORDER, start=1):
        category_grid = access[access["중분류"].eq(category)].copy()
        if category_grid.empty:
            continue

        category_grid["접근성취약도"] = vulnerability_score_from_low_access(category_grid[ACCESS_COL])
        threshold = float(category_grid[ACCESS_COL].quantile(VULNERABLE_QUANTILE))
        vulnerable = category_grid[category_grid[ACCESS_COL].le(threshold)].copy()

        if len(vulnerable) >= DBSCAN_MIN_SAMPLES:
            labels = DBSCAN(eps=DBSCAN_EPS_M, min_samples=DBSCAN_MIN_SAMPLES).fit_predict(
                vulnerable[[X_COL, Y_COL]].to_numpy(dtype="float64")
            )
        else:
            labels = np.full(len(vulnerable), -1, dtype=int)

        prefix = f"H3C{category_idx:02d}"
        vulnerable["DBSCAN_label"] = labels
        vulnerable["취약권역_ID"] = "고립취약격자"
        clustered_mask = vulnerable["DBSCAN_label"].ge(0)
        vulnerable.loc[clustered_mask, "취약권역_ID"] = (
            prefix + "_" + (vulnerable.loc[clustered_mask, "DBSCAN_label"] + 1).astype(str).str.zfill(3)
        )
        vulnerable["하위10pct_접근성기준"] = threshold
        vulnerable["취약선정방식"] = "중분류별 H3SFCA 접근성 하위 10%(동점 포함)"

        clustered = vulnerable[vulnerable["DBSCAN_label"].ge(0)].copy()
        isolated = vulnerable[vulnerable["DBSCAN_label"].lt(0)].copy()
        zero_count = int(vulnerable[ACCESS_COL].eq(0).sum())

        summary_rows.append(
            {
                "중분류": category,
                "분석대상격자수": len(category_grid),
                "하위10pct_접근성기준": threshold,
                "취약격자수": len(vulnerable),
                "취약격자비율": len(vulnerable) / len(category_grid),
                "접근성0_취약격자수": zero_count,
                "접근성0_취약격자비율": zero_count / len(vulnerable) if len(vulnerable) else np.nan,
                "DBSCAN권역포함격자수": len(clustered),
                "고립취약격자수": len(isolated),
                "고립취약격자비율": len(isolated) / len(vulnerable) if len(vulnerable) else np.nan,
                "취약권역수": int(clustered["취약권역_ID"].nunique()),
                "취약격자_대상자수": int(vulnerable[TARGET_POP_COL].sum()),
                "권역포함_대상자수": int(clustered[TARGET_POP_COL].sum()),
                "주요_시군구": top_value(clustered["시군구"]),
                "주요_행정동": top_value(clustered["행정동"]),
            }
        )

        for cluster_id, group in clustered.groupby("취약권역_ID", sort=True):
            weights = group[TARGET_POP_COL].astype(float)
            cluster_rows.append(
                {
                    "중분류": category,
                    "취약권역_ID": cluster_id,
                    "DBSCAN_label": int(group["DBSCAN_label"].iloc[0]),
                    "포함_취약격자수": len(group),
                    "권역면적_m2": len(group) * GRID_AREA_M2,
                    "권역중심_x": float(group[X_COL].mean()),
                    "권역중심_y": float(group[Y_COL].mean()),
                    "문화누리대상자_추정인구수": int(group[TARGET_POP_COL].sum()),
                    "평균_접근성지수": float(group[ACCESS_COL].mean()),
                    "최소_접근성지수": float(group[ACCESS_COL].min()),
                    "평균_접근성취약도": float(group["접근성취약도"].mean()),
                    "수요가중_접근성취약도": weighted_mean(group["접근성취약도"], weights),
                    "평균_접근가능가맹점수": float(group["접근가능_가맹점수"].mean()),
                    "최소_접근가능가맹점수": float(group["접근가능_가맹점수"].min()),
                    "주요_시군구": top_value(group["시군구"]),
                    "주요_행정동": top_value(group["행정동"]),
                }
            )

        vulnerable_rows.append(vulnerable)

    vulnerable_grid = pd.concat(vulnerable_rows, ignore_index=True) if vulnerable_rows else pd.DataFrame()
    cluster_profile = pd.DataFrame(cluster_rows)
    category_summary = pd.DataFrame(summary_rows)

    if not cluster_profile.empty:
        ranked = []
        for _, group in cluster_profile.groupby("중분류", sort=False):
            group = group.sort_values(
                ["수요가중_접근성취약도", "문화누리대상자_추정인구수", "포함_취약격자수"],
                ascending=[False, False, False],
            ).copy()
            group["분류내_취약권역순위"] = np.arange(1, len(group) + 1)
            top_10_n = max(1, math.ceil(len(group) * 0.10))
            top_30_n = max(top_10_n, math.ceil(len(group) * 0.30))
            group["취약권역등급"] = "일반취약권역"
            group.loc[group["분류내_취약권역순위"].le(top_30_n), "취약권역등급"] = "우선취약권역"
            group.loc[group["분류내_취약권역순위"].le(top_10_n), "취약권역등급"] = "최우선취약권역"
            ranked.append(group)
        cluster_profile = pd.concat(ranked, ignore_index=True)

    return vulnerable_grid, cluster_profile, category_summary


def make_grid_gdf(grid: pd.DataFrame) -> gpd.GeoDataFrame:
    half = GRID_SIZE_M / 2
    geometry = [box(x - half, y - half, x + half, y + half) for x, y in zip(grid[X_COL], grid[Y_COL])]
    return gpd.GeoDataFrame(grid.copy(), geometry=geometry, crs="EPSG:5179")


def load_boundaries() -> tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None]:
    dong_path = PROJECT_PATH / "analysis_table" / "data" / "output" / "서울시_시군구_행정동_경계.gpkg"
    gu_json_path = PROJECT_PATH / "analysis_table" / "data" / "input" / "raw" / "spatial" / "boundary" / "seoul_gu_boundary.json"

    if gu_json_path.exists():
        gu_boundary = gpd.read_file(gu_json_path).to_crs(epsg=5179)
        gu_boundary = gu_boundary.rename(columns={"name": "시군구"})
        seoul_boundary = gu_boundary[["geometry"]].dissolve()
        return gu_boundary[["시군구", "geometry"]], seoul_boundary

    if dong_path.exists():
        dong_boundary = gpd.read_file(dong_path)
        if dong_boundary.crs is not None:
            dong_boundary = dong_boundary.to_crs(epsg=5179)
        gu_boundary = dong_boundary[["시군구", "geometry"]].dissolve(by="시군구", as_index=False)
        seoul_boundary = dong_boundary[["geometry"]].dissolve()
        return gu_boundary, seoul_boundary

    return None, None


def draw_base_map(ax: plt.Axes, gu_boundary: gpd.GeoDataFrame | None, seoul_boundary: gpd.GeoDataFrame | None) -> None:
    if seoul_boundary is not None:
        seoul_boundary.plot(ax=ax, color=STYLE["background"], edgecolor=STYLE["text"], linewidth=0.85, zorder=1)
    if gu_boundary is not None:
        gu_boundary.boundary.plot(ax=ax, color=STYLE["axis"], linewidth=0.45, zorder=2)


def draw_gu_labels(ax: plt.Axes, gu_boundary: gpd.GeoDataFrame | None, fontsize: float = 5.5) -> None:
    if gu_boundary is None:
        return
    for _, row in gu_boundary.iterrows():
        point = row.geometry.representative_point()
        label = str(row["시군구"]).replace("구", "")
        ax.text(
            point.x,
            point.y,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=STYLE["text"],
            alpha=0.85,
            zorder=5,
        )


def set_map_extent(ax: plt.Axes, seoul_boundary: gpd.GeoDataFrame | None, data: gpd.GeoDataFrame) -> None:
    if seoul_boundary is not None:
        minx, miny, maxx, maxy = seoul_boundary.total_bounds
    elif not data.empty:
        minx, miny, maxx, maxy = data.total_bounds
    else:
        return

    x_pad = (maxx - minx) * 0.025
    y_pad = (maxy - miny) * 0.025
    ax.set_xlim(minx - x_pad, maxx + x_pad)
    ax.set_ylim(miny - y_pad, maxy + y_pad)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor(STYLE["background"])


def draw_category_map(
    category: str,
    category_gdf: gpd.GeoDataFrame,
    gu_boundary: gpd.GeoDataFrame | None,
    seoul_boundary: gpd.GeoDataFrame | None,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 6.6), dpi=180, facecolor=STYLE["background"])
    draw_base_map(ax, gu_boundary, seoul_boundary)

    if not category_gdf.empty:
        category_gdf.plot(
            ax=ax,
            column="접근성취약도",
            cmap=VULNERABILITY_CMAP,
            norm=VULNERABILITY_NORM,
            linewidth=0,
            alpha=0.94,
            zorder=3,
        )
        category_gdf.dissolve(by="취약권역_ID").boundary.plot(
            ax=ax,
            color=STYLE["cluster_boundary"],
            linewidth=0.38,
            alpha=0.85,
            zorder=4,
        )

    draw_gu_labels(ax, gu_boundary)
    set_map_extent(ax, seoul_boundary, category_gdf)
    ax.set_title(
        f"H3SFCA {category} 취약권역",
        fontsize=17,
        color=STYLE["text"],
        pad=12,
        **TITLE_KWARGS,
    )

    scalar = ScalarMappable(norm=VULNERABILITY_NORM, cmap=VULNERABILITY_CMAP)
    scalar.set_array([])
    cbar = fig.colorbar(scalar, ax=ax, fraction=0.032, pad=0.012)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(labelsize=8.5, colors=STYLE["muted"], length=0)
    cbar.set_label("접근성 취약도", fontsize=9, color=STYLE["muted"], labelpad=8)

    fig.text(
        0.5,
        0.035,
        "중분류별 H3SFCA 접근성 하위 10% 격자를 DBSCAN으로 권역화",
        ha="center",
        va="center",
        fontsize=9.2,
        color=STYLE["muted"],
    )
    fig.tight_layout(rect=[0.02, 0.055, 0.98, 0.965])
    fig.savefig(output_path, dpi=180, bbox_inches="tight", facecolor=STYLE["background"])
    plt.close(fig)


def draw_overview_map(
    clustered_gdf: gpd.GeoDataFrame,
    gu_boundary: gpd.GeoDataFrame | None,
    seoul_boundary: gpd.GeoDataFrame | None,
    output_path: Path,
) -> None:
    fig, axes = plt.subplots(2, 5, figsize=(15.0, 6.9), dpi=180, facecolor=STYLE["background"])
    axes = axes.ravel()

    for ax, category in zip(axes, CATEGORY_ORDER):
        category_gdf = clustered_gdf[clustered_gdf["중분류"].eq(category)].copy()
        draw_base_map(ax, gu_boundary, seoul_boundary)
        if not category_gdf.empty:
            cluster_points = (
                category_gdf.groupby("취약권역_ID", as_index=False)
                .agg(
                    중심점_x=(X_COL, "mean"),
                    중심점_y=(Y_COL, "mean"),
                    접근성취약도=("접근성취약도", "mean"),
                    포함_취약격자수=("GRID_CD", "count"),
                )
            )
            marker_size = np.clip(np.sqrt(cluster_points["포함_취약격자수"]) * 2.2, 2.5, 22)
            ax.scatter(
                cluster_points["중심점_x"],
                cluster_points["중심점_y"],
                c=cluster_points["접근성취약도"],
                cmap=VULNERABILITY_CMAP,
                norm=VULNERABILITY_NORM,
                s=marker_size,
                linewidths=0,
                alpha=0.92,
                zorder=3,
            )
        set_map_extent(ax, seoul_boundary, category_gdf)
        ax.set_title(category, fontsize=12.5, color=STYLE["text"], pad=4, **TITLE_KWARGS)

    for ax in axes[len(CATEGORY_ORDER):]:
        ax.axis("off")

    scalar = ScalarMappable(norm=VULNERABILITY_NORM, cmap=VULNERABILITY_CMAP)
    scalar.set_array([])
    cbar = fig.colorbar(scalar, ax=axes.tolist(), fraction=0.018, pad=0.012)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(labelsize=8.5, colors=STYLE["muted"], length=0)
    cbar.set_label("접근성 취약도", fontsize=9, color=STYLE["muted"], labelpad=8)

    fig.suptitle(
        "H3SFCA 중분류별 취약권역",
        fontsize=22,
        color=STYLE["text"],
        y=0.99,
        **TITLE_KWARGS,
    )
    fig.text(
        0.5,
        0.018,
        "각 중분류 내 H3SFCA 접근성 하위 10% 격자 중 DBSCAN 권역 포함 격자만 표시",
        ha="center",
        va="center",
        fontsize=9.5,
        color=STYLE["muted"],
    )
    fig.subplots_adjust(left=0.02, right=0.94, top=0.90, bottom=0.06, wspace=0.03, hspace=0.12)
    fig.savefig(output_path, dpi=180, bbox_inches="tight", facecolor=STYLE["background"])
    plt.close(fig)


def save_outputs(vulnerable_grid: pd.DataFrame, cluster_profile: pd.DataFrame, category_summary: pd.DataFrame) -> None:
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    IMAGE_PATH.mkdir(parents=True, exist_ok=True)

    vulnerable_grid.to_csv(
        OUTPUT_PATH / "h3sfca_category_dbscan_취약격자.csv",
        index=False,
        encoding="utf-8-sig",
    )
    cluster_profile.to_csv(
        OUTPUT_PATH / "h3sfca_category_dbscan_취약권역.csv",
        index=False,
        encoding="utf-8-sig",
    )
    category_summary.to_csv(
        OUTPUT_PATH / "h3sfca_category_dbscan_분류요약.csv",
        index=False,
        encoding="utf-8-sig",
    )


def draw_maps(vulnerable_grid: pd.DataFrame) -> None:
    gu_boundary, seoul_boundary = load_boundaries()
    clustered = vulnerable_grid[vulnerable_grid["DBSCAN_label"].ge(0)].copy()
    clustered_gdf = make_grid_gdf(clustered)

    for category in CATEGORY_ORDER:
        category_gdf = clustered_gdf[clustered_gdf["중분류"].eq(category)].copy()
        output_path = IMAGE_PATH / f"h3sfca_category_dbscan_{CATEGORY_SLUG[category]}.png"
        draw_category_map(category, category_gdf, gu_boundary, seoul_boundary, output_path)

    draw_overview_map(
        clustered_gdf,
        gu_boundary,
        seoul_boundary,
        IMAGE_PATH / "h3sfca_category_dbscan_all_categories.png",
    )


def build_text_summary(category_summary: pd.DataFrame, cluster_profile: pd.DataFrame) -> dict[str, object]:
    top_by_region = category_summary.sort_values("취약권역수", ascending=False).head(5)
    top_by_population = category_summary.sort_values("권역포함_대상자수", ascending=False).head(5)
    isolated_high = category_summary.sort_values("고립취약격자비율", ascending=False).head(5)

    top_regions = (
        cluster_profile.sort_values(
            ["수요가중_접근성취약도", "문화누리대상자_추정인구수", "포함_취약격자수"],
            ascending=[False, False, False],
        )
        .groupby("중분류", sort=False)
        .head(1)
        [
            [
                "중분류",
                "취약권역_ID",
                "주요_시군구",
                "주요_행정동",
                "포함_취약격자수",
                "문화누리대상자_추정인구수",
                "수요가중_접근성취약도",
            ]
        ]
    )

    return {
        "총_취약권역수": int(cluster_profile["취약권역_ID"].nunique()),
        "총_권역포함격자수": int(category_summary["DBSCAN권역포함격자수"].sum()),
        "총_권역포함대상자수": int(category_summary["권역포함_대상자수"].sum()),
        "취약권역수_상위분류": top_by_region[["중분류", "취약권역수", "권역포함_대상자수", "주요_시군구"]].to_dict("records"),
        "대상자수_상위분류": top_by_population[["중분류", "취약권역수", "권역포함_대상자수", "주요_시군구"]].to_dict("records"),
        "고립비율_상위분류": isolated_high[["중분류", "고립취약격자비율", "취약격자수", "고립취약격자수"]].to_dict("records"),
        "분류별_최상위권역": top_regions.to_dict("records"),
    }


def main() -> None:
    access = load_h3sfca_access()
    vulnerable_grid, cluster_profile, category_summary = run_category_dbscan(access)
    save_outputs(vulnerable_grid, cluster_profile, category_summary)
    draw_maps(vulnerable_grid)

    summary = build_text_summary(category_summary, cluster_profile)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT_PATH={OUTPUT_PATH}")
    print(f"IMAGE_PATH={IMAGE_PATH}")


if __name__ == "__main__":
    main()
