# Folder Guide

이 문서는 최종 발표용 GitHub 저장소에서 어떤 파일을 추적하고 어떤 파일을 제외할지 정리한 기준입니다.

## Tracked Code Folders

| Path | Purpose | Git Policy |
| --- | --- | --- |
| `notebooks/table_design/` | 분석 테이블, 격자 수요, 인구추정, 가맹점, 네트워크, 일반 문화시설 마스터 생성 | notebook과 설명 문서만 추적 |
| `notebooks/eda/` | 이용 현황, 공급-이용 격차, 상관 분석 등 탐색 분석 | `.py`, `.ipynb`, `docs/`만 추적 |
| `notebooks/access/` | 공공 접근성, SFCA/H3SFCA, 취약지수, PCA, 검증 분석 | 번호형 notebook과 `docs/`만 추적 |
| `notebooks/preference/` | 문화시설 선호 수요 ML 실험 | `ML/preference`, `ML/satisfaction`, `docs/`만 추적 |
| `notebooks/dashboard/` | 최종 취약지수, 후보지 추천, 군집/권역화 분석 | notebook, `.py`, `docs/`만 추적 |
| `metadata/` | 데이터 출처, 파일명, 로컬 배치 기준 | 추적 |
| `docs/` | 저장소 사용 가이드와 협업 문서 | 가벼운 문서만 추적 |

## Excluded Folders

| Path or Pattern | Reason |
| --- | --- |
| `data/` | 원천 데이터와 전처리 데이터는 로컬/공유드라이브에서 관리 |
| `analysis_table/` | 이전 작업 구조의 로컬 데이터 위치이며 최종 GitHub 구조에서는 제외 |
| `**/OUTPUT/`, `**/IMAGE/`, `output/`, `outputs/` | notebook 실행 산출물 |
| `notebooks/**/data/`, `notebooks/**/reference/` | 분석 입력 데이터 또는 참고 원문 |
| `scripts/` | 최종 발표용 코드 흐름에서 제외 |
| `docs/assets/`, `docs/share/`, `docs/mnc_dashboard*.html` | 발표/대시보드 생성 산출물 |
| `*.inspect.ndjson`, `codex_build/` | 생성 과정의 검사/빌드 파일 |

`analysis_table/data/...`를 읽는 notebook 경로는 기존 로컬 데이터 보관 위치와의 호환을 위한 참조입니다. 해당 폴더와 데이터 파일은 GitHub 최종 구조에 포함하지 않습니다.

## Naming Rules

- 최종 흐름에 포함되는 notebook은 실행 순서를 알 수 있도록 `01_`, `02_` 형식의 번호를 사용합니다.
- 같은 주제의 설명 문서는 해당 폴더의 `docs/`에 둡니다.
- 산출 표, 이미지, 지도, 모델 파일은 코드 폴더에 두더라도 Git에는 올리지 않습니다.
- 임시 테스트 파일, 개인 실험 파일, 중간 산출물은 main 브랜치에 올리지 않습니다.

## Notebook Rules

- notebook 첫 부분에 목적, 입력 데이터, 출력 결과를 짧게 적습니다.
- 커밋 전 notebook output과 실행 카운트는 비웁니다.
- 경로는 프로젝트 루트 기준으로 작성하고, 실제 데이터는 `metadata/data_metadata.md` 기준으로 로컬에 배치합니다.
