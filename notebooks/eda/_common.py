"""Shared data loading, validation, and output helpers for Kim Sunghyun's EDA."""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


SEOUL_DISTRICTS = (
    "강남구",
    "강동구",
    "강북구",
    "강서구",
    "관악구",
    "광진구",
    "구로구",
    "금천구",
    "노원구",
    "도봉구",
    "동대문구",
    "동작구",
    "마포구",
    "서대문구",
    "서초구",
    "성동구",
    "성북구",
    "송파구",
    "양천구",
    "영등포구",
    "용산구",
    "은평구",
    "종로구",
    "중구",
    "중랑구",
)

CATEGORIES = (
    "도서",
    "음악",
    "영화",
    "TV",
    "공연",
    "전시",
    "공예",
    "사진관",
    "문화체험",
    "직업체험",
    "문화일반",
    "철도",
    "시외고속버스",
    "국내항공",
    "여객선",
    "렌터카",
    "여행사",
    "관광명소",
    "휴양림캠핑장",
    "동식물원",
    "온천",
    "체험관광",
    "테마파크",
    "숙박",
    "스포츠관람",
    "체육용품",
    "체육시설",
)

MERCHANT_USAGE_CATEGORY_MAP = {
    "도서": ("도서",),
    "음악": ("음악",),
    "영상": ("영화", "TV"),
    "공연": ("공연",),
    "미술": ("전시", "공예", "사진관"),
    "문화체험": ("문화체험", "직업체험", "문화일반"),
    "교통수단": ("철도", "시외고속버스", "국내항공", "여객선", "렌터카"),
    "여행사": ("여행사",),
    "관광지": ("관광명소", "휴양림캠핑장", "동식물원", "온천", "체험관광", "테마파크"),
    "숙박": ("숙박",),
    "스포츠관람": ("스포츠관람",),
    "체육용품": ("체육용품",),
    "체육시설": ("체육시설",),
}

AGE_COLUMNS = {
    "issued_under_10": 8,
    "issued_10s": 9,
    "issued_20s": 10,
    "issued_30s": 11,
    "issued_40s": 12,
    "issued_50s": 13,
    "issued_60s": 14,
    "issued_70s": 15,
    "issued_80s": 16,
    "issued_90s": 17,
    "issued_100_plus": 18,
}

ANALYSIS_YEARS = tuple(range(2021, 2026))
USAGE_YEAR = 2025
SUPPLY_SNAPSHOT = "2026-07-06"
RATE_MATCH_TOLERANCE_PP = 0.05
AMOUNT_TOLERANCE_WON = 1.0

USAGE_SOURCE_URL = "https://www.data.go.kr/data/15124183/fileData.do"
MERCHANT_SOURCE_URL = "https://www.mnuri.kr/useOfCard/offlineMerchants.do"


def find_project_root(start: Path | None = None) -> Path:
    """Find the repository root from a script or VS Code session."""

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "data").is_dir() and (candidate / "notebooks").is_dir():
            return candidate
    raise FileNotFoundError(
        "프로젝트 루트를 찾지 못했습니다. Oracle-Project 폴더 안에서 실행해 주세요."
    )


def default_paths(project_root: Path | None = None) -> dict[str, Path]:
    """Return the canonical input and output paths for this EDA."""

    root = project_root or find_project_root()
    return {
        "project_root": root,
        "usage_file": root
        / "data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx",
        "merchant_file": root
        / "data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx",
        "output_dir": root / "notebooks/eda",
    }


def ensure_output_dirs(output_dir: str | Path) -> tuple[Path, Path]:
    """Create and return the table and figure output directories."""

    base = Path(output_dir)
    table_dir = base / "OUTPUT"
    figure_dir = base / "IMAGE"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    return table_dir, figure_dir


def require_columns(
    frame: pd.DataFrame,
    required: Iterable[str],
    *,
    context: str,
) -> None:
    """Raise an actionable error when an analysis input is empty or incomplete."""

    if frame.empty:
        raise ValueError(f"{context} 데이터가 비어 있습니다.")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{context} 필수 열이 없습니다: {', '.join(missing)}")


def save_table(frame: pd.DataFrame, path: Path) -> Path:
    """Write a result table in an Excel-compatible UTF-8 CSV format."""

    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def add_source_footer(fig, *, include_merchants: bool) -> None:
    """Add official verification links without obscuring the analysis area."""

    links = f"이용·발급: {USAGE_SOURCE_URL}"
    if include_merchants:
        links += f" | 오프라인 가맹점: {MERCHANT_SOURCE_URL}"
    fig.text(
        0.5,
        0.008,
        f"공식 출처 확인 링크: {links} · 정확한 원본 식별값(SHA-256)은 EDA README 참조",
        ha="center",
        fontsize=7,
        color="#475569",
    )


def save_figure_with_source_metadata(
    fig,
    save_path: Path,
    *,
    include_merchants: bool,
) -> Path:
    """Save a PNG with the established resolution and source metadata."""

    source_urls = USAGE_SOURCE_URL
    if include_merchants:
        source_urls += f"; {MERCHANT_SOURCE_URL}"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        save_path,
        dpi=180,
        bbox_inches="tight",
        metadata={
            "Author": "Kim Sunghyun / Oracle-Project",
            "Source": source_urls,
            "Description": (
                "Culture Nuri Card EDA. Exact local source-file checksums and "
                "interpretation limits are documented in the EDA README."
            ),
        },
    )
    return save_path


def configure_korean_font() -> str | None:
    """Choose an installed Korean font without requiring a fixed OS."""

    from matplotlib import font_manager, rcParams

    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in (
        "Apple SD Gothic Neo",
        "AppleGothic",
        "Noto Sans CJK KR",
        "NanumGothic",
        "Malgun Gothic",
    ):
        if candidate in available:
            rcParams["font.family"] = candidate
            rcParams["axes.unicode_minus"] = False
            return candidate
    rcParams["axes.unicode_minus"] = False
    return None


def standardize(series: pd.Series) -> pd.Series:
    """Return a population z-score, or zeros when a group has no variation."""

    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    deviation = numeric.std(ddof=0)
    if not math.isfinite(deviation) or deviation == 0:
        return pd.Series(0.0, index=series.index)
    return (numeric - numeric.mean()) / deviation


def concentration_metrics(values: Iterable[float]) -> tuple[float, float, float]:
    """Return CR3, HHI, and Shannon diversity for non-negative amounts."""

    array = np.asarray(list(values), dtype=float)
    total = np.nansum(array)
    if not math.isfinite(total) or total <= 0:
        return np.nan, np.nan, np.nan
    shares = array / total
    positive = shares[shares > 0]
    cr3 = np.sort(shares)[-3:].sum() * 100
    hhi = np.square(shares).sum()
    shannon = -(positive * np.log(positive)).sum()
    return float(cr3), float(hhi), float(shannon)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _clean_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().replace({"": pd.NA})


def _read_excel_safely(*args, **kwargs) -> pd.DataFrame:
    """Read values while silencing one harmless openpyxl extension warning."""

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Unknown extension is not supported and will be removed",
            category=UserWarning,
            module="openpyxl",
        )
        return pd.read_excel(*args, **kwargs)


def _quality_row(
    year: int,
    check: str,
    passed: bool,
    value: float | int | str,
    detail: str,
) -> dict[str, object]:
    return {
        "year": year,
        "check": check,
        "passed": bool(passed),
        "value": value,
        "detail": detail,
    }


def _align_usage_block(
    district_rows: pd.DataFrame,
    right_start: int,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Recover the detached usage block using its two published rates."""

    budget = _numeric(district_rows.iloc[:, 2]).to_numpy(float)
    issued_amount = _numeric(district_rows.iloc[:, 7]).to_numpy(float)
    right = district_rows.iloc[:, right_start:].reset_index(drop=True)
    used_amount = _numeric(right.iloc[:, 0]).to_numpy(float)
    budget_rate = _numeric(right.iloc[:, 3]).to_numpy(float)
    issued_rate = _numeric(right.iloc[:, 4]).to_numpy(float)

    cost = np.empty((len(district_rows), len(district_rows)), dtype=float)
    for left_index in range(len(district_rows)):
        calculated_budget_rate = used_amount / budget[left_index] * 100
        calculated_issued_rate = used_amount / issued_amount[left_index] * 100
        cost[left_index] = (
            np.abs(calculated_budget_rate - budget_rate)
            + np.abs(calculated_issued_rate - issued_rate)
        )

    mapping = np.argmin(cost, axis=1)
    match_error = cost[np.arange(len(district_rows)), mapping]
    if len(np.unique(mapping)) != len(mapping):
        raise ValueError(
            "이용실적 행 복원 결과가 1:1이 아닙니다. 원본 양식 변경 여부를 확인해 주세요."
        )
    if np.nanmax(match_error) > RATE_MATCH_TOLERANCE_PP:
        raise ValueError(
            "이용실적 행 복원 오차가 허용 범위를 초과했습니다: "
            f"{np.nanmax(match_error):.4f}%p"
        )
    return right.iloc[mapping].reset_index(drop=True), mapping, match_error


def _build_usage_year(
    workbook_path: Path,
    year: int,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Load, repair, derive, and validate one yearly source sheet."""

    raw = _read_excel_safely(workbook_path, sheet_name=str(year), header=0)
    district_mask = raw.iloc[:, 1].astype("string").str.strip().isin(SEOUL_DISTRICTS)
    rows = raw.loc[district_mask].reset_index(drop=True)
    right_start = 22 if year == 2025 else 21
    right, mapping, match_error = _align_usage_block(rows, right_start)

    usage = pd.DataFrame(
        {
            "year": year,
            "district": _clean_text(rows.iloc[:, 1]),
            "budget_won": _numeric(rows.iloc[:, 2]),
            "issued_cards": _numeric(rows.iloc[:, 3]),
            "users": _numeric(rows.iloc[:, 4]),
            "issued_male": _numeric(rows.iloc[:, 5]),
            "issued_female": _numeric(rows.iloc[:, 6]),
            "issued_amount_won": _numeric(rows.iloc[:, 7]),
            **{
                column: _numeric(rows.iloc[:, position])
                for column, position in AGE_COLUMNS.items()
            },
            "used_amount_won": _numeric(right.iloc[:, 0]),
            "used_amount_male_won": _numeric(right.iloc[:, 1]),
            "used_amount_female_won": _numeric(right.iloc[:, 2]),
            "budget_utilization_pct": _numeric(right.iloc[:, 3]),
            "issued_utilization_pct": _numeric(right.iloc[:, 4]),
        }
    )

    for position, category in enumerate(CATEGORIES):
        usage[f"amount_{category}"] = _numeric(right.iloc[:, 5 + position])

    usage["transactions"] = _numeric(right.iloc[:, 5 + len(CATEGORIES)])
    usage["culture_experience_transactions"] = _numeric(
        right.iloc[:, 6 + len(CATEGORIES)]
    )
    usage["culture_experience_transaction_pct"] = _numeric(
        right.iloc[:, 7 + len(CATEGORIES)]
    )

    count_start = 8 + len(CATEGORIES)
    for position, category in enumerate(CATEGORIES):
        usage[f"count_{category}"] = _numeric(right.iloc[:, count_start + position])

    usage["user_rate_pct"] = usage["users"] / usage["issued_cards"] * 100
    usage["used_per_issued_won"] = usage["used_amount_won"] / usage["issued_cards"]
    usage["used_per_user_won"] = usage["used_amount_won"] / usage["users"]
    usage["transactions_per_issued"] = usage["transactions"] / usage["issued_cards"]
    usage["average_transaction_won"] = usage["used_amount_won"] / usage["transactions"]
    usage["female_issued_share_pct"] = usage["issued_female"] / usage["issued_cards"] * 100
    senior_columns = [
        "issued_60s",
        "issued_70s",
        "issued_80s",
        "issued_90s",
        "issued_100_plus",
    ]
    usage["senior_60_plus_share_pct"] = (
        usage[senior_columns].sum(axis=1) / usage["issued_cards"] * 100
    )

    amount_columns = [f"amount_{category}" for category in CATEGORIES]
    count_columns = [f"count_{category}" for category in CATEGORIES]
    amount_sum = usage[amount_columns].sum(axis=1)
    count_sum = usage[count_columns].sum(axis=1)
    age_sum = usage[list(AGE_COLUMNS)].sum(axis=1)

    if year == 2025:
        duplicate_issued_amount = _numeric(rows.iloc[:, 21])
        duplicate_issued_diff = (
            duplicate_issued_amount - usage["issued_amount_won"]
        ).abs()
    else:
        duplicate_issued_diff = pd.Series(0.0, index=usage.index)

    rate_budget_diff = (
        usage["used_amount_won"] / usage["budget_won"] * 100
        - usage["budget_utilization_pct"]
    ).abs()
    rate_issued_diff = (
        usage["used_amount_won"] / usage["issued_amount_won"] * 100
        - usage["issued_utilization_pct"]
    ).abs()

    checks = [
        _quality_row(
            year,
            "district_count_is_25",
            len(usage) == 25,
            len(usage),
            "서울 25개 자치구가 모두 존재해야 함",
        ),
        _quality_row(
            year,
            "usage_block_alignment",
            float(np.nanmax(match_error)) <= RATE_MATCH_TOLERANCE_PP,
            float(np.nanmax(match_error)),
            f"행 재배열 {int(np.sum(mapping != np.arange(len(mapping))))}건; 최대 비율 오차(%p)",
        ),
        _quality_row(
            year,
            "issued_sex_sum",
            bool(
                np.allclose(
                    usage["issued_cards"],
                    usage["issued_male"] + usage["issued_female"],
                    atol=0,
                )
            ),
            float(
                (
                    usage["issued_cards"]
                    - usage["issued_male"]
                    - usage["issued_female"]
                ).abs().max()
            ),
            "총 발급매수와 남녀 발급매수 합계의 최대 차이",
        ),
        _quality_row(
            year,
            "issued_age_sum",
            bool(np.allclose(usage["issued_cards"], age_sum, atol=0)),
            float((usage["issued_cards"] - age_sum).abs().max()),
            "총 발급매수와 연령별 발급매수 합계의 최대 차이",
        ),
        _quality_row(
            year,
            "used_sex_amount_sum",
            bool(
                np.allclose(
                    usage["used_amount_won"],
                    usage["used_amount_male_won"] + usage["used_amount_female_won"],
                    atol=AMOUNT_TOLERANCE_WON,
                )
            ),
            float(
                (
                    usage["used_amount_won"]
                    - usage["used_amount_male_won"]
                    - usage["used_amount_female_won"]
                ).abs().max()
            ),
            "총 이용금액과 남녀 이용금액 합계의 최대 차이(원)",
        ),
        _quality_row(
            year,
            "category_amount_sum",
            bool(
                np.allclose(
                    usage["used_amount_won"],
                    amount_sum,
                    atol=AMOUNT_TOLERANCE_WON,
                )
            ),
            float((usage["used_amount_won"] - amount_sum).abs().max()),
            "총 이용금액과 분야별 이용금액 합계의 최대 차이(원)",
        ),
        _quality_row(
            year,
            "category_count_sum",
            bool(np.allclose(usage["transactions"], count_sum, atol=0)),
            float((usage["transactions"] - count_sum).abs().max()),
            "총 이용건수와 분야별 이용건수 합계의 최대 차이",
        ),
        _quality_row(
            year,
            "published_rates",
            bool(
                max(rate_budget_diff.max(), rate_issued_diff.max())
                <= RATE_MATCH_TOLERANCE_PP
            ),
            float(max(rate_budget_diff.max(), rate_issued_diff.max())),
            "공표 이용률과 금액 재계산값의 최대 차이(%p)",
        ),
        _quality_row(
            year,
            "duplicate_issued_amount_2025",
            bool(duplicate_issued_diff.max() <= AMOUNT_TOLERANCE_WON),
            float(duplicate_issued_diff.max()),
            "2025년 중복 발급금액 열의 최대 차이(원); 다른 연도는 0",
        ),
    ]
    return usage, checks


def load_usage_data(
    workbook_path: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and repair the 2021-2025 district usage workbook once."""

    path = Path(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"이용실적 원자료가 없습니다: {path}")

    frames: list[pd.DataFrame] = []
    quality: list[dict[str, object]] = []
    for year in ANALYSIS_YEARS:
        frame, checks = _build_usage_year(path, year)
        frames.append(frame)
        quality.extend(checks)
    usage = pd.concat(frames, ignore_index=True)
    return usage, pd.DataFrame(quality)


def _district_from_address(address: pd.Series) -> pd.Series:
    alternatives = "|".join(sorted(SEOUL_DISTRICTS, key=len, reverse=True))
    return address.astype("string").str.extract(f"({alternatives})", expand=False)


def load_merchant_data(
    workbook_path: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load, standardize, flag, and de-duplicate the merchant snapshot once."""

    path = Path(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"가맹점 원자료가 없습니다: {path}")

    raw = _read_excel_safely(path, sheet_name=0, header=None)
    rows = raw.iloc[2:].reset_index(drop=True)
    merchants = pd.DataFrame(
        {
            "merchant_name": _clean_text(rows.iloc[:, 1]),
            "merchant_type": _clean_text(rows.iloc[:, 2]),
            "category_large": _clean_text(rows.iloc[:, 3]),
            "category_mid": _clean_text(rows.iloc[:, 4]),
            "category_small": _clean_text(rows.iloc[:, 5]),
            "latitude": _numeric(rows.iloc[:, 6]),
            "longitude": _numeric(rows.iloc[:, 7]),
            "usage_info": _clean_text(rows.iloc[:, 8]),
            "discount_yn": _clean_text(rows.iloc[:, 9]),
            "discount_detail": _clean_text(rows.iloc[:, 10]),
            "metro": _clean_text(rows.iloc[:, 11]),
            "district_reported": _clean_text(rows.iloc[:, 12]),
            "address": _clean_text(rows.iloc[:, 13]),
            "modified_at": pd.to_datetime(rows.iloc[:, 14], errors="coerce"),
            "registered_at": pd.to_datetime(rows.iloc[:, 15], errors="coerce"),
            "keywords": _clean_text(rows.iloc[:, 16]),
            "url": _clean_text(rows.iloc[:, 17]),
            "registration_actor": _clean_text(rows.iloc[:, 18]),
            "service_types": _clean_text(rows.iloc[:, 19]),
            "phone_payment_detail": _clean_text(rows.iloc[:, 20]),
            "service_detail": _clean_text(rows.iloc[:, 21]),
        }
    )
    merchants = merchants.loc[merchants["merchant_name"].notna()].reset_index(drop=True)
    merchants["district_reported"] = merchants["district_reported"].str.strip()
    merchants["district_from_address"] = _district_from_address(merchants["address"])
    merchants["district_mismatch"] = (
        merchants["district_from_address"].notna()
        & merchants["district_reported"].notna()
        & (merchants["district_from_address"] != merchants["district_reported"])
    )
    merchants["district"] = merchants["district_from_address"].fillna(
        merchants["district_reported"]
    )
    merchants["coordinate_valid"] = (
        merchants["latitude"].between(37.3, 37.8)
        & merchants["longitude"].between(126.7, 127.3)
    )
    service_text = merchants[["service_types", "service_detail"]].fillna("").agg(
        " ".join, axis=1
    )
    merchants["phone_payment_available"] = (
        service_text.str.contains("전화결제", na=False)
        | merchants["phone_payment_detail"].notna()
    )
    merchants["visiting_service_available"] = service_text.str.contains(
        "찾아가는 문화서비스", na=False
    )
    merchants["disabled_friendly_available"] = service_text.str.contains(
        "장애인친화시설", na=False
    )
    merchants["exact_duplicate"] = merchants.duplicated(
        subset=["merchant_name", "address"], keep="first"
    )

    analysis = merchants.loc[~merchants["exact_duplicate"]].copy()
    analysis = analysis.loc[analysis["district"].isin(SEOUL_DISTRICTS)].reset_index(
        drop=True
    )
    quality = pd.DataFrame(
        [
            {
                "check": "raw_merchant_rows",
                "value": len(merchants),
                "detail": "헤더 2행 제외 후 가맹점명 존재 행",
            },
            {
                "check": "exact_duplicate_rows",
                "value": int(merchants["exact_duplicate"].sum()),
                "detail": "동일 가맹점명·동일 주소의 후속 중복행",
            },
            {
                "check": "analysis_merchant_rows",
                "value": len(analysis),
                "detail": "완전 중복 제거 및 서울 자치구 확인 후 분석 행",
            },
            {
                "check": "invalid_coordinate_rows",
                "value": int((~analysis["coordinate_valid"]).sum()),
                "detail": "서울 범위 밖, 0 또는 결측 좌표; 지도 분석에서 제외",
            },
            {
                "check": "district_address_mismatch_rows",
                "value": int(merchants["district_mismatch"].sum()),
                "detail": "기초 필드와 주소에서 추출한 자치구가 다른 행; 주소 기준 사용",
            },
        ]
    )
    return merchants, analysis, quality


def build_district_summary(usage: pd.DataFrame, year: int = USAGE_YEAR) -> pd.DataFrame:
    """Return one row per district with current-year concentration metrics."""

    require_columns(
        usage,
        ["year", "district", "issued_utilization_pct", *[f"amount_{c}" for c in CATEGORIES]],
        context="자치구 이용실적",
    )
    summary = usage.loc[usage["year"] == year].copy()
    if len(summary) != 25:
        raise ValueError(f"{year}년 자치구가 25개가 아닙니다: {len(summary)}")

    amount_columns = [f"amount_{category}" for category in CATEGORIES]
    concentration = summary[amount_columns].apply(
        lambda row: concentration_metrics(row), axis=1
    )
    summary[["cr3_amount_pct", "hhi_amount", "shannon_amount"]] = pd.DataFrame(
        concentration.tolist(), index=summary.index
    )
    return summary.sort_values("issued_utilization_pct", ascending=False).reset_index(
        drop=True
    )


def build_merchant_supply(merchants: pd.DataFrame) -> pd.DataFrame:
    """Create district-level current merchant supply indicators."""

    require_columns(
        merchants,
        [
            "district",
            "category_mid",
            "coordinate_valid",
            "phone_payment_available",
            "visiting_service_available",
            "disabled_friendly_available",
        ],
        context="가맹점 분석",
    )
    rows: list[dict[str, object]] = []
    for district in SEOUL_DISTRICTS:
        group = merchants.loc[merchants["district"] == district]
        category_counts = group["category_mid"].value_counts(dropna=True)
        _, hhi, shannon = concentration_metrics(category_counts.to_numpy())
        rows.append(
            {
                "district": district,
                "merchant_count": len(group),
                "valid_coordinate_count": int(group["coordinate_valid"].sum()),
                "category_mid_count": int(group["category_mid"].nunique()),
                "merchant_hhi": hhi,
                "merchant_shannon": shannon,
                "phone_payment_count": int(group["phone_payment_available"].sum()),
                "visiting_service_count": int(
                    group["visiting_service_available"].sum()
                ),
                "disabled_friendly_count": int(
                    group["disabled_friendly_available"].sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def build_usage_supply_relationship(
    usage: pd.DataFrame,
    merchant_supply: pd.DataFrame,
    usage_year: int = USAGE_YEAR,
) -> pd.DataFrame:
    """Join recent usage and current supply for exploratory association only."""

    district = build_district_summary(usage, usage_year)
    combined = district.merge(merchant_supply, on="district", how="left", validate="1:1")
    combined["merchants_per_1000_issued"] = (
        combined["merchant_count"] / combined["issued_cards"] * 1000
    )
    supply_median = combined["merchants_per_1000_issued"].median()
    usage_median = combined["issued_utilization_pct"].median()
    combined["supply_level"] = np.where(
        combined["merchants_per_1000_issued"] >= supply_median,
        "공급 높음",
        "공급 낮음",
    )
    combined["usage_level"] = np.where(
        combined["issued_utilization_pct"] >= usage_median,
        "이용 높음",
        "이용 낮음",
    )
    combined["supply_usage_type"] = (
        combined["supply_level"] + " · " + combined["usage_level"]
    )
    return combined
