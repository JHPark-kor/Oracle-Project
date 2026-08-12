# 선호모델 빠른 사용법

필요한 작업 하나만 선택하면 됩니다. **접근성 담당자는 대부분 1번만 사용하면 됩니다.**

## 1. 접근성 계산에 선호수요 넣기

[Drive 배포 폴더](https://drive.google.com/drive/folders/1UocOuxEMJd0V_t1jdI2fiA73CpsWiZoP)에서
`grid_middle_category_preference_demand_2024.csv`를 받습니다.

| 구분 | 값 |
|---|---|
| 선호 결과 키 | `GRID_CD`, `middle_category` |
| H3SFCA 키 | `GRID_CD`, `중분류` |
| H3SFCA 수요로 쓸 열 | `potential_demand_absolute` |

현재 H3SFCA 노트북에서 격자 전체 대상자 수로 만든 `grid_demand` 대신 다음처럼
분야별 수요를 만듭니다.

```python
import pandas as pd
from src.preference_analysis.inference import build_h3sfca_demand_table

preference = pd.read_csv("grid_middle_category_preference_demand_2024.csv")
grid_demand = build_h3sfca_demand_table(preference)

# H3SFCA 첫 번째 chunk 반복문의 기존 GRID_CD 단독 결합을 교체
chunk = chunk.merge(
    grid_demand,
    on=["GRID_CD", "중분류"],
    how="inner",
    validate="many_to_one",
)
```

이후 시설 유효수요부터 H3SFCA를 다시 계산합니다. 완성된 H3SFCA 점수에 선호확률을
나중에 곱하는 방식은 사용하지 않습니다.

> `음악`, `체육용품`은 선호모델 미산출 분야입니다. `0`으로 채우지 말고 `NA`로
> 유지합니다. 상세 분야 규칙은 `accessibility_category_contract.csv`에 있습니다.

## 2. 성별·연령으로 새 선호확률 예측하기

프로젝트 루트에서 모델 전용 환경을 설치합니다.

```bash
python -m pip install -r models/preference_analysis/v1/requirements.txt
```

```python
from pathlib import Path
import pandas as pd
from src.preference_analysis.inference import (
    load_preference_pipeline,
    predict_probability_frame,
)

model = load_preference_pipeline(
    Path("models/preference_analysis/v1/preference_model_pipeline.joblib")
)

input_df = pd.DataFrame([
    {"sex_code": 1, "age_code": 2, "survey_year": 2024}
])
result = predict_probability_frame(model, input_df)
```

입력 코드는 다음 세 개뿐입니다.

- `sex_code`: `1=남성`, `2=여성`
- `age_code`: `1=15~19세`, `2=20대`, …, `7=70대 이상`
- `survey_year`: 공간 적용 시 `2024`

`predict_probability_frame()`이 입력을 검사하고 클래스명이 붙은 확률 열을 반환하므로
클래스 순서를 직접 하드코딩할 필요가 없습니다. Joblib에는 프로젝트 코드가 필요하므로
모델 파일 하나만 떼어 쓰지 말고 이 Git 브랜치 전체를 사용합니다.

## 3. 처음부터 전부 다시 계산하기

1. [Drive 입력데이터 폴더](https://drive.google.com/drive/folders/1SbP5LCWb3gx6lHZd_ZUe2uQVZolssFEE)에서
   `preference_pipeline_inputs_v1.zip`을 받습니다.
2. ZIP을 `Oracle-Project` 루트에 압축 해제합니다.
3. VS Code에서 `00_preference_pipeline_run_all.ipynb`를 열고 **Run All**을 누릅니다.

노트북 경로:

```text
notebooks/exploratory_eda/kim_sunghyun/machine_learning/
00_preference_pipeline_run_all.ipynb
```

## 파일을 찾을 때

| 파일 | 용도 |
|---|---|
| `preference_model_pipeline.joblib` | 학습모델과 전처리 Pipeline |
| `model_contract.json` | 입력 코드북, 클래스 순서, 버전, SHA-256 |
| `activity_category_mapping.csv` | 설문 활동코드 1~88 매핑 |
| `accessibility_category_contract.csv` | 접근성 10개 분야 연결 규칙 |
| `example_input.csv`, `example_output.csv` | 예시 입출력 |

모델은 실제 카드 이용확률이 아니라 **만족활동 1·2·3순위 기반 경험선호 확률**입니다.
계산식·검증·한계는 [`docs/preference_analysis.md`](../../../docs/preference_analysis.md)를
참고하세요.
