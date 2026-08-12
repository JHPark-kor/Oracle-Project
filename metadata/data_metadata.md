# Data Metadata

프로젝트 데이터 폴더와 파일명을 영어 기준으로 정리한 설명서입니다. 실제 데이터 파일은 GitHub에 올리지 않고, 팀원 각자의 로컬 환경 또는 공유 드라이브에서 같은 경로로 관리합니다.

| Path | Description |
| --- | --- |
| `data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx` | 서울시 문화누리카드 이용 및 발급 실적 데이터입니다. |
| `data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx` | 서울 오프라인 문화누리카드 가맹점 목록입니다. |
| `data/raw/franchise_candidates/source/small_business_market_area_seoul_202603.csv` | 서울 상가/상권 기반 후보 가맹점 탐색용 데이터입니다. |
| `data/raw/demographics/welfare/seoul_basic_livelihood_recipients_by_dong_202405.xlsx` | 동별 국민기초생활 수급자 현황 데이터입니다. |
| `data/raw/demographics/welfare/seoul_near_poverty_by_age_dong_20210731.csv` | 동별/연령별 차상위계층 현황 데이터입니다. |
| `data/raw/demographics/senior/source/seoul_senior_by_dong_20260714.xlsx` | 동별 고령자 현황 데이터입니다. |
| `data/raw/demographics/disabled/source/seoul_disabled_by_age_dong_20260714.xlsx` | 동별/연령별 장애인 현황 데이터입니다. |
| `data/raw/preferences/source/culture_art_activity_survey/` | 국민문화예술활동조사 필요 컬럼 정리 데이터입니다. |
| `data/raw/preferences/source/leisure_activity_survey/` | 국민여가활동조사 필요 컬럼 정리 데이터입니다. |
| `data/raw/preferences/source/survey_design_docs/` | 문화예술/여가활동조사 조사표와 파일설계서입니다. |
| `data/raw/surveys/leisure_2021_2025.csv` | 2021~2025 국민여가활동조사 통합 마이크로데이터입니다. 만족활동 1~3순위와 설문가중치를 선호모델에 사용합니다. |
| `data/raw/spatial/grid_pop_access.csv` | 100m 격자코드·행정동코드·EPSG:5179 중심점·추정인구 연결표입니다. 선호모델에서는 접근성 열을 사용하지 않습니다. |
| `data/processed/preference_analysis/population/grid_sex_age_target_population_model_input_2024.csv` | 100m 격자별 성별×모델연령 문화누리 대상자 추정인구 입력입니다. 15세 이상 공간 적용에 사용합니다. |
| `data/processed/preference_analysis/model/` | 순위가중 다항 로지스틱 모델, 성별×연령별 2024 절대확률, 개발·시간 외 검증 결과입니다. |
| `data/processed/preference_analysis/spatial/` | 격자·행정동·자치구별 정책 8개 분야 절대확률·잠재수요, 외적 타당성, 정합성 검증 및 인터랙티브 지도입니다. |
| `models/preference_analysis/v1/` | 원시 입력 검증을 포함한 경량 선호모델 Pipeline, 입력·클래스 계약, 활동 매핑표, H3SFCA 중분류 계약과 합성 예시 입출력입니다. 행 단위 원자료는 포함하지 않습니다. |
| `data/raw/transport/bus_stations/source/seoul_bus_stations.csv` | 서울시 버스정류소 위치정보입니다. |
| `data/raw/transport/subway_stations/source/seoul_subway_stations.csv` | 서울시 지하철 역사 정보입니다. |
| `data/raw/spatial/boundary/seoul_gu_boundary.json` | 서울시 구 경계 지도 데이터입니다. |
| `data/raw/spatial/grid/source/` | 서울시 격자 공간데이터입니다. |
| `data/raw/spatial/base_map/map_visual/` | 서울시 수치지도 기반 공간자료입니다. |
| `data/raw/spatial/dem/source/` | 서울시 DEM 지형 데이터입니다. |
| `docs/references/reports/mnc_package_reports/` | 문화누리카드 정책보고서, 만족도 조사, 선행연구 PDF 자료의 로컬 보관 위치입니다. |

## Notes

- GitHub에는 실제 원자료·대용량 처리자료를 올리지 않습니다. `models/`의 검토된
  경량 배포 묶음은 입력계약·버전·해시를 포함하고 행 단위 원자료가 없을 때만 예외로
  추적할 수 있습니다.
- `Reports/`와 `mnc_package_reports/`에 중복으로 있던 PDF는 `mnc_package_reports/` 기준으로 정리했습니다.
- 팀원은 이 문서의 경로와 동일하게 데이터를 배치한 뒤 notebook과 `src/` 코드를 실행합니다.
