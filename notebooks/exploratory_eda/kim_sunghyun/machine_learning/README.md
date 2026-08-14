# 김성현 선호분석 노트북

원하는 작업 하나만 선택하면 됩니다.

| 하고 싶은 일 | 열 파일 |
|---|---|
| 저장된 결과만 빠르게 보기 | `01_preference_results_overview.ipynb` |
| 전체 파이프라인 다시 실행 | `00_preference_pipeline_run_all.ipynb` |
| 모델 계산·검증 상세 보기 | `02_multinomial_preference_model.ipynb` |
| 100m·행정동 공간 적용 상세 보기 | `03_spatial_preference_application.ipynb` |

## VS Code 실행

1. `Oracle-Project` 폴더 전체를 VS Code로 엽니다.
2. 노트북 우측 상단에서 프로젝트 `.venv` 커널을 선택합니다.
3. 원하는 노트북을 열고 **Run All**을 누릅니다.

전체 재실행 전에 [Drive 입력데이터 폴더](https://drive.google.com/drive/folders/1SbP5LCWb3gx6lHZd_ZUe2uQVZolssFEE)의
`preference_pipeline_inputs_v1.zip`을 프로젝트 루트에 압축 해제합니다. 모델 학습을
포함하므로 `00`은 수 분 걸릴 수 있습니다.

## 결과 위치

- 모델 결과: `data/processed/preference_analysis/model/`
- 격자·행정동·자치구 결과: `data/processed/preference_analysis/spatial/`
- 지도: `data/processed/preference_analysis/spatial/maps/`
- 팀 전달용 모델: `models/preference_analysis/v1/`

접근성 담당자는 노트북을 다시 실행할 필요 없이
[모델 빠른 사용법](../../../../models/preference_analysis/v1/README.md)의 1번과
[Drive 배포 폴더](https://drive.google.com/drive/folders/1UocOuxEMJd0V_t1jdI2fiA73CpsWiZoP)의
100m 격자 CSV를 사용하면 됩니다.

결과는 실제 이용확률이 아닌 **만족활동 기반 선호확률·잠재수요 추정치**입니다.
음악 활동은 원본 라벨을 보존한 채 `기타·문화누리 비대응`에 포함되며, 접근성
모델에서 음악·체육용품의 선호수요를 `0`으로 간주하지 않습니다.
