# 김성현 문화누리카드 EDA 실행 안내

## 폴더 구조

```text
notebooks/eda/
├── README.md
├── docs/
│   ├── kosis_data_inventory.md
│   ├── kosis_existing_data_comparison.md
│   ├── kosis_recommended_downloads.md
│   └── kosis_search_log.md
├── IMAGE/
├── OUTPUT/
├── reference/
├── run_kim_sunghyun_eda.py
├── _common.py
├── eda_01_annual_usage_diversity.py
├── eda_02_district_usage_supply_diagnostic.py
├── eda_03_category_usage_supply_gap.py
└── eda_04_supply_utilization_sensitivity.py
```

`access` 폴더와 맞춰 주요 표는 `OUTPUT`, 주요 이미지는 `IMAGE`에 저장합니다.

## 실행

프로젝트 루트에서 실행합니다.

```bash
python notebooks/eda/run_kim_sunghyun_eda.py
```

## 입력 파일

```text
data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx
data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx
```

## 분석 코드와 산출물

| 코드 파일 | 담당 분석 | 주요 산출물 |
|---|---|---|
| `eda_01_annual_usage_diversity.py` | 연도별 이용·다양성 | 연간 이용표, 다양성표, Figure 1 |
| `eda_02_district_usage_supply_diagnostic.py` | 자치구 종합진단 | 자치구 진단표, Figure 2 |
| `eda_03_category_usage_supply_gap.py` | 분야별 이용-공급 불일치 | 불일치 후보표, Figure 3 |
| `eda_04_supply_utilization_sensitivity.py` | 공급-이용 상관 민감도 | 상관 민감도표, Figure 4 |

## 생성 결과

```text
notebooks/eda/OUTPUT/
├── kim_sunghyun_annual_card_issuance_usage_utilization_metrics.csv
├── kim_sunghyun_annual_category_concentration_diversity_metrics.csv
├── kim_sunghyun_district_five_year_utilization_supply_diagnostic.csv
├── kim_sunghyun_category_usage_supply_gap_candidates.csv
└── kim_sunghyun_merchant_supply_utilization_correlation_sensitivity.csv

notebooks/eda/IMAGE/
├── kim_sunghyun_01_annual_card_usage_and_category_diversity_trends.png
├── kim_sunghyun_02_district_five_year_utilization_supply_diagnostic.png
├── kim_sunghyun_03_category_usage_supply_gap_heatmap.png
└── kim_sunghyun_04_merchant_supply_utilization_correlation_sensitivity.png
```

## 해석 주의

- 이 EDA는 최종 취약지역 판정이 아니라 추가 검토 우선순위를 정하는 예비 진단입니다.
- 2025 이용실적과 2026-07-06 가맹점 스냅숏은 기준시점이 달라 인과관계로 해석하지 않습니다.
- 이용자 거주지·가맹점 소재지 기준, 역외 이용, 온라인 이용을 확인하기 전에는 공급 부족으로 확정하지 않습니다.
- 문화누리 대상자 수와 행정동·격자 접근성을 결합한 뒤 최종 정책 우선지역을 판단해야 합니다.
