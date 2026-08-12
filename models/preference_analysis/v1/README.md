# 만족활동 기반 선호모델 handoff v1

이 폴더는 다른 팀원이 모델을 재학습하지 않고 선호확률을 계산하거나 최신
H3SFCA 접근성 코드에 잠재수요를 연결할 수 있도록 만든 배포 묶음입니다.

동일한 파일과 사전 계산된 100m 격자 결과는 Google Drive의
[분류데이터/선호확률_모델_배포_v1](https://drive.google.com/drive/folders/1UocOuxEMJd0V_t1jdI2fiA73CpsWiZoP)에 있습니다.
Git 반영 전에도 전체 전달 코드를 함께 받으려면 그 폴더의
`preference_model_handoff_v1.zip`을 프로젝트 루트에 압축 해제하면 됩니다.

## 요청 항목과 파일

| 항목 | 제공 위치 |
|---|---|
| 1. 학습된 모델 객체 | `preference_model_pipeline.joblib` 내부 `classifier` |
| 2. 전처리·전체 Pipeline | `preference_model_pipeline.joblib` |
| 3. 입력 컬럼 목록 | `model_contract.json`의 `input_contract` |
| 4. 입력 변수 코드북 | `model_contract.json`의 `input_contract.codebook` |
| 5. `predict_proba` 클래스 순서 | `model_contract.json`의 `predict_proba_contract.class_order` |
| 6. 카테고리 매핑표 | `activity_category_mapping.csv` |
| 7. 예시 입력·출력 | `example_input.csv`, `example_output.csv` |

환경 고정 파일은 `requirements.txt`입니다. 배포 Pipeline에는 이 저장소의
`src.preference_analysis.inference.PreferenceInputTransformer`가 포함되므로,
Joblib만 따로 복사하지 말고 Git 브랜치 전체 또는 `src/`가 포함된 Drive ZIP을
사용해야 합니다.

`accessibility_category_contract.csv`는 최신 H3SFCA의 10개 중분류와 선호모델
8개 정책 분야의 결합 가능 여부를 명시합니다.

Drive에 함께 둔 `grid_middle_category_preference_demand_2024.csv`는 접근성
담당자가 모델을 다시 실행하지 않고 결합할 수 있는 100m 격자 결과입니다.

- 행 수: `484,224` (`60,528개 격자 × 8개 정책 분야`)
- 결합 키: `(GRID_CD, middle_category)`
- SHA-256: `427b9775aec490e1b64d8827adbad2edfbb54aeec5b15e552de366c843443f77`

## 바로 예측하기

프로젝트 루트에서 실행합니다. Joblib은 신뢰된 이 저장소의 파일만 로드하세요.

macOS/Linux:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r models/preference_analysis/v1/requirements.txt
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r models/preference_analysis/v1/requirements.txt
```

이 모델의 검증 환경은 Python `3.13.13`, NumPy `2.5.1`, pandas `3.0.3`,
scikit-learn `1.9.0`, joblib `1.5.3`이며 정확한 값은 `model_contract.json`에도
기록되어 있습니다.

```python
from pathlib import Path
import pandas as pd

from src.preference_analysis.inference import (
    load_preference_pipeline,
    predict_probability_frame,
)

bundle = Path("models/preference_analysis/v1")
model = load_preference_pipeline(bundle / "preference_model_pipeline.joblib")

input_df = pd.DataFrame(
    [{"sex_code": 1, "age_code": 2, "survey_year": 2024}]
)
result = predict_probability_frame(model, input_df)
print(result)
```

배포 Pipeline은 원시 입력 3개를 검증한 뒤 내부에서 다음 값을 생성합니다.

```text
sex_age_code = str(sex_code) + "_" + str(age_code)
```

입력 코드:

- `sex_code`: `1=남성`, `2=여성`
- `age_code`: `1=15~19세`, `2=20대`, `3=30대`, `4=40대`,
  `5=50대`, `6=60대`, `7=70대 이상`
- `survey_year`: `2021~2025`; 2024년 공간 결과에는 `2024` 사용

정확한 `predict_proba()` 배열 순서는 하드코딩하지 말고 항상 다음처럼 읽습니다.

```python
classes = (
    model.named_steps["preference_model"]
    .named_steps["classifier"]
    .classes_
)
probabilities = model.predict_proba(input_df)
probability_df = pd.DataFrame(probabilities, columns=classes)
```

## 최신 H3SFCA에 선호 잠재수요 넣기

2026-08-11의 `origin/main` H3SFCA 결과 계약을 기준으로 검증했습니다.

- 접근성 키: `(접근수단, GRID_CD, 중분류)`
- 선호 격자 키: `(GRID_CD, middle_category)`
- 공통 분야: 도서, 영상, 공연, 미술, 문화체험, 관광지, 스포츠관람, 체육시설
- 접근성 전용 `음악`, `체육용품`: 선호모델 **미산출**이며 `0`이 아님

선호 반영 H3SFCA를 다시 계산할 때는 다음 헬퍼로 분야별 수요를 만듭니다.

```python
import pandas as pd

from src.preference_analysis.inference import build_h3sfca_demand_table

preference = pd.read_csv(
    "data/processed/preference_analysis/spatial/"
    "grid_middle_category_preference_demand_2024.csv"
)
grid_demand = build_h3sfca_demand_table(preference)

# 기존 grid_demand=grid_meta[...] 생성 코드를 위 테이블로 교체한 뒤,
# H3SFCA의 첫 번째 chunk loop에서 기존 GRID_CD 단독 merge도 아래처럼 교체
chunk = chunk.merge(
    grid_demand,
    on=["GRID_CD", "중분류"],
    how="inner",
    validate="many_to_one",
)
```

현재 H3SFCA 노트북의 격자 전체 대상자 수 대신 `수요인구수`, 즉
`potential_demand_absolute`를 사용해 시설 유효수요부터 다시 계산해야 합니다.
완성된 H3SFCA 값에 선호확률만 사후 곱하는 것은 같은 계산이 아닙니다.

이미 계산된 H3SFCA 결과와 검토용으로 결합할 때는 다음을 사용할 수 있습니다.

```python
from src.preference_analysis.inference import merge_preference_with_h3sfca

combined = merge_preference_with_h3sfca(accessibility, preference)
```

접근성 행이 없는 격자·분야를 임의로 `0`으로 채우지 마세요. 접근성 담당자의
무자료 정의를 적용해야 합니다. 또한 `preference_share_conditional_mnc`가 아니라
`potential_demand_absolute`를 H3SFCA의 절대 수요에 사용합니다.

## 모델 의미와 환경

- 목표: 국민여가활동조사 만족활동 1·2·3순위의 3:2:1 가중 경험선호
- 입력: 성별×연령 결합코드와 조사연도
- 출력: 정책 8개 분야와 `기타·문화누리 비대응`을 포함한 9개 절대확률
- 학습: 2021~2024년, 2025년 시간 외 평가
- 모델은 실제 카드 이용확률이나 개인 추천 결과가 아닙니다.

생성 환경은 `model_contract.json`의 `runtime`에 기록되어 있습니다. Joblib 호환을
위해 가능하면 동일한 Python·scikit-learn 버전을 사용하세요.

## 배포 묶음 다시 만들기

로컬에서 모델 학습 산출물을 갱신한 뒤 다음 명령을 실행합니다.

```bash
.venv/bin/python -m src.preference_analysis.export_handoff --project-root .
```

Windows PowerShell에서는 다음과 같습니다.

```powershell
.\.venv\Scripts\python.exe -m src.preference_analysis.export_handoff --project-root .
```

그다음 테스트합니다.

```bash
.venv/bin/python -m pytest tests/preference_analysis/test_inference.py -q
```

```powershell
.\.venv\Scripts\python.exe -m pytest tests/preference_analysis/test_inference.py -q
```
