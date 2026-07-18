# Folder Guide

이 문서는 `oracle_mnc_project`의 폴더를 어떤 용도로 사용할지 정리한 기준입니다.

| Path | Purpose | Git Policy |
| --- | --- | --- |
| `data/raw/` | 원천 데이터 저장 위치 | `.gitkeep`만 추적, 실제 데이터 제외 |
| `data/interim/` | 전처리 중간 산출물 | `.gitkeep`만 추적, 실제 데이터 제외 |
| `data/processed/` | 분석용 최종 전처리 데이터 | `.gitkeep`만 추적, 실제 데이터 제외 |
| `metadata/` | 데이터 출처, 파일명, 컬럼, 사용 계획 | 추적 |
| `notebooks/exploratory_eda/` | 탐색적 데이터 분석 notebook | 의미 있는 notebook만 추적 |
| `notebooks/policy_validation_eda/` | 정책 검증 및 가설 확인 notebook | 의미 있는 notebook만 추적 |
| `src/` | 재사용 가능한 전처리, 분석, 시각화 코드 | 추적 |
| `docs/` | 팀 가이드, 분석 메모, 참고 문서 설명 | 가벼운 문서만 추적 |
| `docs/references/reports/` | 보고서 PDF 위치 설명 | PDF 원본 제외, README만 추적 |

## Naming Rules

- 폴더명과 파일명은 영어 소문자, 숫자, `_`를 사용합니다.
- 개인 실험 파일은 브랜치에서 작업하고, 공유할 수준이 되면 이름을 명확히 바꿔 Pull Request로 올립니다.
- 임시 확인용 파일명에는 `test_`를 붙이고 main에는 올리지 않습니다.

## Notebook Rules

- notebook 첫 셀에는 목적, 입력 데이터, 출력 결과를 간단히 적습니다.
- 실행 결과가 너무 커지면 출력은 정리한 뒤 커밋합니다.
- 데이터 파일 경로는 `metadata/data_metadata.md` 기준 경로를 사용합니다.
