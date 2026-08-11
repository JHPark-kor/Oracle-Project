# 만족활동 기반 선호예측 파이프라인

## 분석 목적

국민여가활동조사 2021~2025년의 `가장 만족스러운 여가활동 1·2·3순위`를
3:2:1로 결합해 성별×연령별 경험기반 선호확률을 추정합니다. 2024년 서울시
100m 격자별 성별×연령별 문화누리 대상자 추정인구에 절대확률을 적용해
격자·행정동·자치구별 잠재수요를 계산합니다.

향후 희망활동, 가맹점 수, 거리, 이동시간, E2SFCA 등 접근성 변수는 사용하지
않습니다. 결과는 미래 희망이나 실제 이용자 수가 아니라 `만족활동 기반 추정치`입니다.

## 최종 모델

| 항목 | 정의 |
| --- | --- |
| 목표변수 | 만족활동 1·2·3순위의 순위가중 중분류 |
| 순위점수 | 1순위 3, 2순위 2, 3순위 1 |
| 입력변수 | 성별×연령 결합코드, 수치형 조사연도 |
| 모델 | 설문가중 단일 다항 로지스틱 회귀 |
| 클래스 | 정책 9개 분야 + `기타·문화누리 비대응` |
| 선택 설정 | 성별×연령 결합형, `C=0.1` |
| 모델 선택 | 2022~2024 순차연도검증 50% + 2021~2024 응답자 그룹 5-Fold 50% |
| 최종 평가 | 2021~2024 재학습 후 2025 시간 외 평가 |
| 공간 확률 조건 | 조사연도 2024 |

응답자 $i$의 분야 $c$ 유효가중치는 다음과 같습니다.

$$
w_{ic}=w_i\frac{\sum_{r\in R_i}q_rI(y_{ir}=c)}{\sum_{r\in R_i}q_r},
\qquad(q_1,q_2,q_3)=(3,2,1)
$$

2·3순위 결측 시 관측된 순위점수 합으로 나누며, 동일 중분류가 여러 순위에
나오면 점수를 합산합니다. 응답자별 유효가중치 합은 원 설문 최종가중치와 같습니다.

2025 시간 외 평가의 Log Loss는 1.6279로 가중 사전확률 baseline(1.6666)보다
2.32% 개선됐습니다. 다만 Accuracy는 두 모델 모두 약 40.61%로 같으므로, 이
모델은 개인의 최고 선호분야 추천이 아니라 성별×연령 집단의 확률 배분에 사용합니다.

## 확률과 잠재수요

- `preference_probability_absolute`: 기타를 포함한 10개 클래스 절대확률 $p(c)$
- `other_probability_absolute`: 기타·문화누리 비대응 절대확률
- `preference_share_conditional_mnc`: $p(c)/(1-p(other))$, 정책 9개 내부 상대구성
- `potential_demand_absolute`: 대상자 수에 절대확률을 곱한 잠재수요

격자 $g$의 분야 $c$ 잠재수요는 다음과 같습니다.

$$
D_{g,c}=\sum_{s,a}N_{g,s,a}p_{s,a,c}
$$

조건부 구성비는 비교·표시용이며 절대 잠재수요 계산에는 사용하지 않습니다.
정책 9개 잠재수요 합이 대상자 수보다 작을 수 있으며, 차이는 기타 잠재수요입니다.

## 실행 순서

### VS Code 실행 버튼

1. VS Code에서 프로젝트 루트를 엽니다.
2. Python 인터프리터로 `.venv/bin/python`을 선택합니다.
3. `Run and Debug`에서 아래 구성을 순서대로 실행합니다.

```text
Preference 1 - Validate mapping
Preference 2 - Train and validate model
Preference 3 - Align grid population
Preference 4 - Build spatial outputs and maps
Preference tests
```

`Preference 2`는 다년도·5-Fold 검증으로 실행시간이 가장 깁니다. 계산된 모델과
공간 입력을 그대로 사용할 때는 `Preference 4`만 다시 실행해도 됩니다.

### Terminal

```bash
# Oracle-Project 루트에서 실행
.venv/bin/python -m src.preference_analysis.build_mapping --project-root .
.venv/bin/python -m src.preference_analysis.train_model --project-root .
.venv/bin/python -m src.preference_analysis.align_population --project-root .
.venv/bin/python -m src.preference_analysis.build_spatial_outputs --project-root .
.venv/bin/python -m pytest tests/preference_analysis -q
```

노트북만으로 전체 파이프라인을 실행하거나 결과를 확인하려면 다음 순서를 사용합니다.

```text
notebooks/exploratory_eda/kim_sunghyun/machine_learning/00_preference_pipeline_run_all.ipynb
notebooks/exploratory_eda/kim_sunghyun/machine_learning/01_preference_results_overview.ipynb
notebooks/exploratory_eda/kim_sunghyun/machine_learning/02_multinomial_preference_model.ipynb
notebooks/exploratory_eda/kim_sunghyun/machine_learning/03_spatial_preference_application.ipynb
```

`00`은 매핑→모델→인구 정렬→공간 결과·지도→테스트를 순서대로 재실행합니다.
`01`은 저장된 핵심 결과만 빠르게 확인하며, `02`와 `03`은 모델과 공간 적용의
상세 계산·해석용 노트북입니다.

## 결과 위치

### 모델

```text
data/processed/preference_analysis/model/
├── multinomial_logistic_2021_2024.joblib
├── multinomial_model_metadata.json
├── sex_age_middle_category_preference_2024.csv
├── model_score_temporal_2022_2025.csv
├── model_validation_2024_by_category.csv
├── model_validation_2025_by_category.csv
├── model_calibration_by_sex_age_2024.csv
├── model_calibration_by_sex_age_2025.csv
└── model_calibration_summary_2024_2025.csv
```

### 공간·외적 타당성·지도

```text
data/processed/preference_analysis/spatial/
├── grid_middle_category_preference_demand_2024.csv
├── dong_middle_category_preference_demand_2024.csv
├── gu_middle_category_preference_demand_2024.csv
├── spatial_validation_summary_2024.csv
├── external_validation_2024_by_gu_category.csv
├── external_validation_2024_by_gu.csv
├── external_validation_2024_by_category.csv
├── external_validation_2024_summary.csv
├── external_validation_2024_crosswalk_sensitivity.csv
├── external_validation_card_crosswalk_v1.csv
├── external_validation_arts_2024_by_sex_age.csv
├── external_validation_arts_2024_summary.csv
├── spatial_preference_run_metadata_2024.json
└── maps/
    ├── grid_preference_demand_2024.html
    └── dong_preference_demand_2024.html
```

HTML은 미리 계산된 결과를 여는 정적 지도이며, 열 때 모델을 재학습하지 않습니다.
CSV를 보존하므로 이후 접근성 결과와 `GRID_CD` 또는 행정동코드로 결합할 수 있습니다.

## 외적 타당성 해석

2024년 자치구별 카드 이용건수·금액 중 설정한 crosswalk로 매핑한 정책 9개 분야를
연결합니다. 카드 이용건수를 주 비교값으로 사용하고, 가격 차이에 민감한 이용금액은
보조 민감도 지표로 사용합니다.

`공예`와 `문화일반`의 매핑 선택에 결과가 민감할 수 있어 주 매핑, 기존 EDA식,
보수적 제외 방식의 요약을 별도 sensitivity 파일에 저장합니다. 국민문화예술활동조사
비교는 서울 표본이 아니라 2024년 전국 조사표본의 성별×연령 방향성 점검입니다.

`예측 선호 ≠ 실제 이용`입니다. 차이는 모델 Accuracy나 오차율이 아니라 접근성,
공급, 가격, 정보, 거래빈도 등이 반영된 구성 차이입니다. 특히 높은 예측선호와 낮은
실제 이용 조합은 이후 접근성·공급 분석에서 확인할 가설입니다.

## Impact/Risk Analysis

- 기존 7-theme 코드와 산출물은 삭제하거나 덮어쓰지 않습니다.
- 기존 `preference_probability` 컬럼을 유지해 하위호환성을 보존합니다.
- 100m 결과는 관측값이 아니라 추정치이며 작은 격자일수록 불확실성이 큽니다.
- 대상자 0명 격자는 확률 무자료로 표시하며 0%로 해석하지 않습니다.
- 지도 색상 분위는 대상자 양수 지역만으로 계산한 분야별 상대 구간이므로 서로 다른
  분야의 색 농도를 직접 비교하지 않습니다.
- 60,528개 격자를 포함한 HTML은 용량이 크고 느린 컴퓨터에서 여는 데 수 초가
  걸릴 수 있습니다. geometry를 한 번만 저장해 18개 중복 레이어는 만들지 않습니다.
- 행정동 지도는 2024 추정치를 2025-06-30 단순화 경계에 코드로 결합한 표시용
  지도입니다. 격자의 행정동 소속은 기존 2024 연결표를 유지합니다.
- 카드실적의 자치구가 이용자 거주지 기준인지 이용지 기준인지 원본만으로 확정할 수
  없으므로 지역별 외적 타당성 결과는 방향성 점검으로만 해석합니다.
- HTML은 정적 계산결과지만 Leaflet 라이브러리와 OpenStreetMap 배경지도를 온라인에서
  불러오므로 완전 오프라인에서는 배경지도와 상호작용이 렌더링되지 않을 수 있습니다.
