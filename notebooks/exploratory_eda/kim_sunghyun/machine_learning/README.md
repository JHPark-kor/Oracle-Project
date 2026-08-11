# 김성현 수요·선호 머신러닝 실행 안내

이 폴더는 Git에서 팀과 공유하는 정식 실행·결과 확인 노트북 모음입니다.

## 실행 순서

1. `00_preference_pipeline_run_all.ipynb`
   - 중분류 매핑 검증 → 모델 학습·검증 → 100m 성별·연령별 대상인구 정렬
     → 격자·행정동·자치구 결과와 지도 생성 → 전체 테스트를 순서대로 실행합니다.
   - 모델 다년도 검증 때문에 전체 실행에는 수 분이 걸릴 수 있습니다.
2. `01_preference_results_overview.ipynb`
   - 재학습 없이 저장된 모델 성능, 성별×연령별 확률, 공간 검증과 핵심 결과를
     빠르게 확인합니다.
3. `02_multinomial_preference_model.ipynb`
   - 만족활동 1·2·3순위의 3:2:1 가중치, 다항 로지스틱 선택, C·변수구조 검증,
     2025 시간 외 평가를 상세히 확인합니다.
4. `03_spatial_preference_application.ipynb`
   - 성별×연령별 절대 선호확률을 100m 대상자 추정인구에 적용하고 행정동·자치구로
     집계하는 계산과 검증을 상세히 확인합니다.

## VS Code에서 실행

1. `Oracle-Project` 폴더 전체를 VS Code로 엽니다.
2. 우측 상단 커널에서 프로젝트의 `.venv` Python을 선택합니다.
3. 처음부터 다시 만들려면 `00`을 열고 **Run All**을 누릅니다.
4. 계산 결과만 보려면 `01`을 열고 **Run All**을 누릅니다.

## 코드와 결과 위치

- 계산 코드: `src/preference_analysis/`
- 자동 테스트: `tests/preference_analysis/`
- 모델 결과: `data/processed/preference_analysis/model/`
- 공간 결과: `data/processed/preference_analysis/spatial/`
- 지도: `data/processed/preference_analysis/spatial/maps/`
- 실행 로그: `data/processed/preference_analysis/run_logs/`

`data/raw`와 `data/processed`는 용량과 개인정보·재현성 관리를 위해 Git에 올리지
않습니다. 팀원은 원자료를 지정된 경로에 준비한 뒤 `00`을 실행해 같은 산출물을
생성해야 합니다. HTML 지도는 미리 계산된 결과를 여는 정적 파일이며, 열 때 모델을
다시 학습하지 않습니다.

## 해석 주의

- 결과는 미래 희망이 아니라 **만족활동 기반 선호확률과 잠재수요 추정치**입니다.
- 100m 결과는 관측값이 아니므로 정책 해석에는 행정동 집계도 함께 사용합니다.
- 접근성, 가맹점 수, 거리, 이동시간은 이 모델에 포함되지 않습니다.
