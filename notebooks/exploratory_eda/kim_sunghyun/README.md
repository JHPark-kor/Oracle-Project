# 김성현 핵심 EDA 실행 안내

## 파일 구조

```text
notebooks/exploratory_eda/kim_sunghyun/
├── README.md
├── run_kim_sunghyun_eda.py
├── _common.py
├── eda_01_annual_usage_diversity.py
├── eda_02_district_usage_supply_diagnostic.py
├── eda_03_category_usage_supply_gap.py
└── eda_04_supply_utilization_sensitivity.py
```

- 전체 실행 파일: `run_kim_sunghyun_eda.py`
- 공통 원자료 복원·품질검사·저장 기능: `_common.py`
- 분석별 계산·결과표·그래프: `eda_01`~`eda_04`
- 로컬 결과: `data/processed/kim_sunghyun_card_usage_supply_gap_eda/`

원본 Excel 두 개는 전체 실행 중 각각 한 번만 읽습니다. 데이터 품질검사, 2021~2023년
원본 행 복원, 2025년 중복 발급금액 열 확인, 가맹점 중복 제거는 `_common.py`에서
자동 수행하지만 별도의 발표용 EDA 산출물로 만들지는 않습니다.

## 분석 코드와 산출물 대응

| 코드 파일 | 담당 분석 | 생성 표 | 생성 이미지 |
| --- | --- | --- | --- |
| `eda_01_annual_usage_diversity.py` | 연도별 이용·다양성 | 연간 이용표, 다양성표 | Figure 1 |
| `eda_02_district_usage_supply_diagnostic.py` | 자치구 종합진단 | 자치구 진단표 | Figure 2 |
| `eda_03_category_usage_supply_gap.py` | 분야별 이용–공급 불일치 | 불일치 후보표 | Figure 3 |
| `eda_04_supply_utilization_sensitivity.py` | 공급–이용 상관 민감도 | 상관 민감도표 | Figure 4 |

## 입력 파일

```text
data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx
data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx
```

## 데이터 출처와 원본 검증

| 분석 원본 | 제공·획득 경로 | 공식 확인 링크 | 현재 원본 SHA-256 |
| --- | --- | --- | --- |
| `mnc_seoul_usage_issuance_2021_2025.xlsx` | 한국문화예술위원회가 정보공개청구를 통해 제공한 서울 25개 자치구 2021–2025년 이용·발급 실적. 파일 작성자 메타데이터 `arko`, 2026-07-13 수령 | [정보공개포털](https://www.open.go.kr/othicInfo/infoList/infoList.do), [한국문화예술위원회 발급실적·사용통계 공식 카탈로그](https://www.data.go.kr/data/15124183/fileData.do) | `131d34f38a2e2548564d70e9ec72fe068ddb3cfa2de7cd04adc074967b434024` |
| `mnc_seoul_offline_merchants_20260706.xlsx` | 한국문화예술위원회 오프라인 가맹점 2026-07-06 스냅숏. 파일 작성자 메타데이터 `arko`, 분석 유효행 4,727개 | [문화누리카드 공식 오프라인 가맹점 검색](https://www.mnuri.kr/useOfCard/offlineMerchants.do), [공공데이터포털 오프라인 가맹점 카탈로그](https://www.data.go.kr/data/15045194/fileData.do) | `dbea7609690a8eba139c3fefd7f4a42b820a1c3d3595c5afec8503e9322daac4` |

공공데이터포털의 발급실적·사용통계 자료는 관련 공식 카탈로그와 샘플이며,
현재 분석에 사용한 2021–2025년 전체 원본과 동일한 공개 다운로드 파일은 아닙니다.
따라서 정확한 재현에는 정보공개로 받은 로컬 원본과 아래 SHA-256이 모두 일치해야 합니다.

```bash
shasum -a 256 data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx
shasum -a 256 data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx
```

생성되는 네 이미지에는 사용한 공식 확인 링크가 하단에 표시되며, PNG의
`Source` 메타데이터에도 같은 URL이 저장됩니다.

## VS Code 실행

1. 프로젝트 루트에서 가상환경을 만들고 `pip install -r requirements.txt`를 실행합니다.
2. VS Code에서 Python 및 Jupyter 확장을 설치합니다.
3. 프로젝트 루트의 터미널에서 다음 명령을 실행합니다.

```bash
python notebooks/exploratory_eda/kim_sunghyun/run_kim_sunghyun_eda.py
```

4. VS Code에서 실행하려면 `run_kim_sunghyun_eda.py`를 열고 `.venv/bin/python`을
   인터프리터로 선택한 뒤 `Run Python File`을 누릅니다.

성공하면 표 5개와 이미지 4개의 전체 경로가 터미널에 출력됩니다. 같은 명령을
다시 실행하면 동일한 파일을 안전하게 갱신하며 별도 중복 파일은 만들지 않습니다.

## 남긴 핵심 분석

1. 서울시 2021–2025년 발급·이용·소진율 및 분야 다양성 변화
2. 자치구별 5개년 이용률 수준·추세와 현재 공급 예비 진단
3. 동일 분야의 발급자당 이용강도–현재 가맹점 공급강도 불일치 후보
4. 중심지역 제외에 따른 단순 공급–이용 상관 민감도

## 핵심 산출물

```text
data/processed/kim_sunghyun_card_usage_supply_gap_eda/
├── figures/
│   ├── kim_sunghyun_01_annual_card_usage_and_category_diversity_trends.png
│   ├── kim_sunghyun_02_district_five_year_utilization_supply_diagnostic.png
│   ├── kim_sunghyun_03_category_usage_supply_gap_heatmap.png
│   └── kim_sunghyun_04_merchant_supply_utilization_correlation_sensitivity.png
└── tables/
    ├── kim_sunghyun_annual_card_issuance_usage_utilization_metrics.csv
    ├── kim_sunghyun_annual_category_concentration_diversity_metrics.csv
    ├── kim_sunghyun_district_five_year_utilization_supply_diagnostic.csv
    ├── kim_sunghyun_category_usage_supply_gap_candidates.csv
    └── kim_sunghyun_merchant_supply_utilization_correlation_sensitivity.csv
```

- 자치구 종합표는 최종 취약지역이 아니라 추가 검토 우선순위를 정하는 예비 진단입니다.
- Figure 2에는 서울 25개 자치구가 모두 점으로 포함되며, 혼잡을 줄이기 위해 정책
  우선 검토 유형에 해당하는 10개 자치구만 이름을 표시합니다.
- 분야별 후보 CSV는 불일치 점수 1 이상이며 분야별 상위 3개 조합만 남깁니다.
- 2025 이용실적과 2026-07-06 가맹점은 기준시점이 다르므로 인과관계로 해석하지 않습니다.
- 이용자 거주지·가맹점 소재지 기준과 역외·온라인 이용을 확인하기 전에는 공급 부족으로 확정하지 않습니다.
- 문화누리 대상자 수와 행정동·격자 접근성을 결합한 후 최종 정책 우선지역을 결정합니다.

## Figure 3 읽는 방법: 분야별 이용–공급 불일치

- 세로축은 문화누리 가맹점 중분류, 가로축은 서울 25개 자치구입니다.
- 같은 분야 안에서 자치구별 `발급자당 이용금액`, `발급자 1천 명당 이용건수`,
  `발급자 1천 명당 현재 가맹점 수`를 각각 z-score로 표준화합니다.
- 계산식은 `불일치 점수 = (이용금액 z + 이용건수 z) / 2 - 가맹점 공급 z`입니다.
- 빨강이 진할수록 해당 분야의 관측 이용은 상대적으로 강하지만 현재 지역 내
  가맹점 공급은 상대적으로 약한 조합입니다. 신규 가맹점·역외이용 확인 후보입니다.
- 파랑이 진할수록 현재 공급은 상대적으로 강하지만 관측 이용은 약한 조합입니다.
  정보·가격·품목 정합성 또는 실제 수요를 추가 점검합니다.
- 흰색에 가까우면 이용강도와 현재 공급강도가 서울 내에서 대체로 비슷합니다.
- 예를 들어 강서구–공연의 점수는 약 `5.03`으로 가장 강한 양의 불일치 후보입니다.
  그러나 온라인 구매나 다른 자치구 가맹점 이용이 포함될 수 있으므로 공급 부족으로
  바로 확정하면 안 됩니다.

## Figure 4 읽는 방법: 공급–이용 상관 민감도

- 공급지표는 `2026-07-06 현재 발급자 1천 명당 오프라인 가맹점 수`, 이용지표는
  `2025년 발급금액 대비 이용률`입니다.
- Pearson은 선형관계를 보고 특이값에 민감하며, Spearman은 순위관계를 보므로
  종로구처럼 가맹점이 집중된 지역의 영향을 덜 받습니다.
- 전체 25개 구의 Pearson은 약 `-0.247`, Spearman은 약 `0.068`입니다.
- 종로구 등을 제외하면 계수의 부호와 크기가 바뀌지만 모두 약한 수준이고,
  5,000회 순열검정 p-value도 모든 시나리오에서 `0.19`보다 큽니다.
- 따라서 현재 자료에서는 “가맹점 수가 많은 자치구일수록 이용률이 높다”는 일관된
  관계를 확인할 수 없습니다. 이는 가맹점이 중요하지 않다는 뜻이 아니라, 공급의
  분야·거리·품질·온라인 및 역외이용과 기준시점 차이를 함께 봐야 한다는 뜻입니다.
