# OCI MNCDEV 빠른 사용법

## 팀원이 실제로 할 일

이미 데이터 이전이 완료된 뒤에는 OCI 01~21을 다시 실행할 필요가 없다.
팀원은 아래 네 단계만 진행한다.

1. GitHub에서 프로젝트를 받은 뒤 `requirements.txt`와
   `requirements-oci.txt`를 설치한다.
2. 본인 권한으로 `MNCDEV` Wallet을 내려받아 프로젝트 밖
   `~/.oci/wallets/MNCDEV/`에 둔다.
3. `config/oci.env.example`을 `.env.oci.local`로 복사하고 현재 프로젝트
   계정 `MNC_APP`과 Wallet 경로를 적는다. 비밀번호는 파일에 적지 않는다.
4. VS Code에서 `OCI 02 - Check MNCDEV connection`을 실행한다.

관리자는 데이터 갱신 때만 OCI 04~20을 사용한다. 일반 팀원은 조회와 분석에
필요한 실행 항목만 사용한다.

| 하려는 일 | 실행 또는 함수 |
|---|---|
| Oracle 연결 확인 | `OCI 02 - Check MNCDEV connection` |
| 카드·가맹점 EDA 재실행 | `OCI 11 - Run EDA with Oracle card and merchant` |
| 전체 적재 상태 확인 | `OCI 22 - Check full project Oracle readiness` |
| 15세 이상 격자 대상자 조회 | `load_grid_model_input()` |
| 선호확률·격자 잠재수요 조회 | `load_preference_data()` |
| 기존 H3SFCA 조회 | `load_accessibility_data()` |

Oracle에서 읽는 값은 기존 로컬 결과를 별도 데이터로 교체한 것이 아니다.
각 이전 단계에서 같은 키와 수치를 대조해 모두 일치한 결과만 적재했다.

## 저장 위치

- 원본 CSV·XLSX·ZIP·공간파일: OCI Object Storage
- 분석용 정규화 데이터: Autonomous Database `MNCDEV`
- 코드·DDL·테스트·설정 예시: GitHub
- Wallet과 비밀번호: 각 팀원 컴퓨터에만 보관

Wallet은 GitHub, VS Code 프로젝트 폴더, Google Drive, 메신저에 올리지 않는다.

## 처음 한 번 준비

1. OCI 관리자가 팀원을 프로젝트 그룹에 추가하고 필요한 최소 권한을 부여한다.
2. 팀원은 OCI Console에서 Tokyo 리전의 `MNCDEV`를 연다.
3. `Database connection` → `Download wallet`에서 Instance Wallet을 각자 내려받는다.
4. 프로젝트 루트에서 OCI 의존성을 설치한다.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-oci.txt
```

5. Wallet을 프로젝트 밖에 설치하고 권한을 제한한다.

```bash
mkdir -p ~/.oci/wallets/MNCDEV
unzip ~/Downloads/Wallet_MNCDEV.zip -d ~/.oci/wallets/MNCDEV
chmod 700 ~/.oci/wallets/MNCDEV
chmod 600 ~/.oci/wallets/MNCDEV/*
```

6. 로컬 설정 파일을 만든다. 이 파일은 `.gitignore`로 제외된다.

```bash
cp config/oci.env.example .env.oci.local
```

현재 구현에서는 사용자명을 `MNC_APP`으로 설정하고 각자의 Wallet 경로만
수정한다. 비밀번호는 적지 않는다.

```env
DATA_BACKEND=oracle
ORACLE_DB_USER=MNC_APP
ORACLE_DB_DSN=mncdev_low
ORACLE_DB_WALLET_DIR=~/.oci/wallets/MNCDEV
```

Object Storage 업로드 담당자는 OCI 보안 세션이 만료됐을 때 다음 명령으로
다시 인증한다. 가상환경 안의 CLI를 직접 지정하므로 `oci: command not found`를
피할 수 있다.

```bash
.venv/bin/oci session authenticate \
  --region ap-tokyo-1 \
  --profile-name MNC_SETUP
```

## VS Code에서 연결 확인

1. 프로젝트 전체 폴더를 VS Code로 연다.
2. Python 인터프리터를 `.venv`로 선택한다.
3. Run and Debug에서 `OCI 02 - Check MNCDEV connection`을 실행한다.
4. 터미널에 DB 비밀번호와 Wallet 비밀번호를 직접 입력한다.
5. `database_connection_ok`가 나오면 연결 성공이다.

비밀번호는 입력 중 화면에 표시되지 않으며 파일에도 저장되지 않는다.

## 계정 원칙

- `ADMIN`: 최초 테이블·역할·사용자 생성에만 사용한다.
- 현재 개발단계: 신뢰된 팀원만 프로젝트 계정 `MNC_APP`을 사용한다.
- `MNC_APP` 비밀번호는 GitHub·Drive·메신저에 올리지 않고 승인된 안전한
  경로로 별도 전달한다.
- 운영 전환 전: 개인별 읽기 전용 계정과 ETL 계정을 분리하는 추가 작업이
  필요하다. 현재 저장소에는 개인계정 자동 생성 기능이 포함되지 않는다.
- 팀원에게 `ADMIN` 비밀번호는 공유하지 않는다.

Wallet을 분실하거나 Git에 올렸다면 OCI에서 Wallet을 즉시 회전한 뒤 모든
팀원이 새 Wallet을 다시 내려받는다.

## 최초 프로젝트 계정과 테이블 만들기

DB 연결 확인 후 관리자가 한 번 실행한다.

1. `.env.oci.local`의 `ORACLE_DB_USER`가 `ADMIN`인지 확인한다.
2. VS Code의 Run and Debug에서
   `OCI 03 - Bootstrap MNC_APP schema`를 실행한다.
3. 터미널에서 ADMIN 비밀번호, Wallet 비밀번호, 새 MNC_APP 비밀번호를
   순서대로 직접 입력한다.
4. `bootstrap_ok`가 나오면 생성이 완료된 것이다.
5. `.env.oci.local`의 사용자만 다음처럼 바꾼다.

```env
ORACLE_DB_USER=MNC_APP
```

6. `OCI 02 - Check MNCDEV connection`을 다시 실행하고 MNC_APP 비밀번호로
   접속되는지 확인한다.

생성 대상만 미리 보려면 다음 명령을 사용한다. 이 명령은 DB를 변경하지 않는다.

```bash
.venv/bin/python scripts/bootstrap_oracle_database.py --plan
```

스크립트를 다시 실행해도 기존 MNC_APP 비밀번호를 바꾸거나 기존 테이블을
삭제하지 않는다. 누락된 테이블만 추가하고 조회 View만 최신 정의로 갱신한다.

현재 생성되는 범위는 다음과 같다.

- 원본 파일 메타데이터와 ETL 실행이력
- 행정구역 및 분류체계·분류 매핑
- 카드 이용실적 원본 27분류 staging
- 자치구 연도별 카드 이용 fact
- 자치구 연도별 13중분류 카드 이용 fact와 조회 View
- 자치구 연도별 성별 발급·이용 및 연령별 발급 fact
- 2026-07-06 가맹점 snapshot
- 100m 격자 위치·행정동 차원
- 100m 격자 성별×통일연령 추정 대상자 fact
- 15세 이상 선호모델 입력 View

선호확률과 기존 H3SFCA 접근성 결과도 각각 별도 버전으로 이관한다.

## 첫 데이터 이전: 카드 이용실적

전체 데이터 이전 전에 카드 이용실적으로 Object Storage와 Database 흐름을
검증한다.

1. Run and Debug에서 `OCI 04 - Upload card raw file`을 실행한다.
2. 출력의 `status`가 `uploaded` 또는 `already_uploaded`인지 확인한다.
3. `OCI 05 - Load card usage to Oracle`을 실행한다.
4. MNC_APP 비밀번호와 Wallet 비밀번호를 입력한다.
5. `database_load_ok`와 다음 행 수를 확인한다.

```text
자치구: 25
원 이용분류: 27
공급 중분류: 13
자치구×연도: 125
자치구×연도×13중분류: 1,625
통합 전후 금액·건수 불일치: 0
```

같은 SHA-256 원본의 성공 이력이 있으면 `already_loaded`를 출력하고 다시
적재하지 않는다. 원본 27분류는 staging에 보존하고, 분석 테이블에는 기존
검증 매핑으로 합산한 13중분류를 적재한다.

OCI 04는 namespace와 객체경로가 담긴
`.oci_card_upload_receipt.local.json`을 자동으로 만든다. 이 파일에는
비밀번호·API 키가 없지만 개인별 실행상태이므로 Git에는 올리지 않는다.

## 로컬 결과와 Oracle 값 대조

DB 적재 후 Run and Debug에서 `OCI 06 - Verify card local vs Oracle`을
실행한다. 이 검증은 단순히 행 수만 비교하지 않고 다음 모든 값을 키별로
대조한다.

- 원본 27분류 3,375행의 이용금액·이용건수
- 자치구×연도 125행의 발급·예산·이용 값
- 자치구×연도×13중분류 1,625행의 이용금액·이용건수
- 자치구×연도×성별 250행과 자치구×연도×연령 1,375행

`parity_ok`와 여섯 검사의 `passed: true`가 모두 나오기
전에는 기존 EDA의 입력을 Oracle 조회로 바꾸지 않는다.

금액·건수·발급매수 등 정수 값은 허용오차 0으로 완전일치해야 한다.
`culture_exp_pct`만 Python 실수와 Oracle `NUMBER(12,8)`의 표현 차이를 고려해
절대오차 `1e-8` 이하를 같은 값으로 판정한다. 이는 실제 데이터값을 보정하거나
변경하는 처리가 아니다.

## 기존 EDA를 Oracle 카드 데이터로 실행

`OCI 06`에서 기본 테이블 다섯 개와 `EDA 공통 입력 전체 88열`까지 모두
`passed: true`인지 확인한 후에만 실행한다.

1. Run and Debug에서 `OCI 07 - Run EDA with Oracle card data`를 실행한다.
2. MNC_APP 비밀번호와 Wallet 비밀번호를 입력한다.
3. 기존 EDA와 같은 표 5개·이미지 4개가 생성되는지 확인한다.

분석 계산 코드는 바꾸지 않는다. 카드 이용 DataFrame만 Oracle 정규화 테이블에서
기존 125행×88열 형태로 복원해 전달한다. 현재 가맹점 원본은 아직 로컬 Excel을
사용하므로 완전한 cloud-only 실행은 아니며, 가맹점이 다음 이전 대상이다.

## 두 번째 데이터 이전: 오프라인 가맹점

카드 이전이 완료된 다음 아래 순서로 진행한다.

1. `OCI 08 - Upload merchant raw file`
2. `OCI 09 - Load merchant snapshot to Oracle`
3. `OCI 10 - Verify merchant local vs Oracle`
4. `OCI 11 - Run EDA with Oracle card and merchant`

OCI 08은 원본 XLSX를 다음 Object Storage 경로에 보관한다.

```text
landing/merchants/2026-07-06/mnc_seoul_offline_merchants_20260706.xlsx
```

OCI 09는 기존 EDA 전처리를 그대로 재사용한다. 원본 4,727행에서 동일한
가맹점명·주소의 후속 중복 5행을 제외한 4,722행을 Oracle에 적재한다.
좌표 이상 16행과 신고구·주소구 불일치 37행은 삭제하지 않고 품질 flag로
보존한다. 같은 원본 SHA-256의 성공 이력이 있으면 중복 적재하지 않는다.

OCI 10에서는 4,722개 가맹점의 29개 EDA 입력 열과 품질검사 5개가 모두
`passed: true`인지 확인한다. OCI 11은 카드와 가맹점을 모두 Oracle에서 읽되,
EDA 01~04의 계산식과 결과 파일명은 그대로 유지한다.

가맹점 snapshot은 2026-07-06 기준이고 카드 이용은 2021~2025이므로 두 자료를
같은 시점의 관측값으로 해석하지 않는다. 또한 EDA의 4,722개 기준은 서울
bounding box와 주소 자치구를 사용한 집계 기준이다. 정밀 서울 경계 결합을 거친
공간 접근성용 4,702개 기준과는 별도로 관리한다.

## 세 번째 데이터 이전: 100m 격자 성별·연령별 추정 대상자

다음 순서대로 실행한다.

1. `OCI 12 - Upload grid population inputs`
2. `OCI 13 - Load grid population to Oracle`
3. `OCI 14 - Verify grid population local vs Oracle`
4. `OCI 15 - Check preference grid input from Oracle`

OCI 12는 격자 lookup을 raw bucket에, 성별·연령별 추정 대상자 입력을 artifact
bucket의 `standardized/target_population/2024/`에 저장한다. 두 파일의 해시와
Object Storage URI는 각각 로컬 receipt에 기록되며 비밀번호는 기록하지 않는다.

OCI 13은 기존 `population_alignment.py`를 그대로 호출한다. 원본 12개 연령대를
임의로 다시 나누지 않고 다음 9개로 통일한다.

```text
0~5세, 6~14세, 15~19세, 20대, 30대, 40대, 50대, 60대, 70세 이상
```

전체 1,089,504행은 `FACT_GRID_TARGET_SEX_AGE`에 보존하고, 15세 이상 7개
연령대 847,392행은 `VW_GRID_TARGET_MODEL_INPUT`으로 조회한다. 15세 미만을
다른 연령대에 배분하지 않는다.

OCI 14는 격자 60,528개의 전체 SHA-256, 원본 총량 582,549명,
성별×연령 18개 및 행정동×성별×연령 전체 집계, 대표 격자 50개의 원행 전체
열, 15세 이상 총량 545,692명과 426개 행정동을 대조한다. 원격 DB의 108만
행 문자열 전체를 내려받지 않아도 값·분포·공간 배분을 검증하도록 구성했다.
다섯 검사가 모두 `passed: true`여야 한다. OCI 15의
`model_input_ready`는 기존 선호모델의 15열 입력 형식으로 Oracle 조회가
가능하다는 뜻이다. OCI 15는 847,392행 전체를 VS Code로 내려받지 않고
Oracle 내부에서 행 수·키·총량·결측·음수·기준연도·proxy 표식을 집계한 뒤
요약값 한 행만 받아오므로 준비 상태를 빠르게 확인한다. 실제 분석에서만
전체 모델 입력을 조회한다.

이 대상자 수는 실제 문화누리카드 대상자 명부가 아니다. 기초생활수급자와
차상위계층 추정치를 단순 합산한 proxy이며 자격군 간 중복을 조정하지 않았다.
따라서 DB에도 `proxy_flag=Y`, `overlap_adjusted=N`으로 저장한다.

## 네 번째 데이터 이전: 선호모델과 잠재수요 산출물

먼저 `OCI 16 - Upload preference model and outputs`를 실행한다. 업로드 전에
모델 파일 SHA-256이 계약서와 같은지, 확률·격자·행정동·자치구 결과의 행 수가
각각 126, 484,224, 3,408, 200인지, 공간검증 8개가 모두 `pass`인지 확인한다.

통과한 파일은 `mnc-artifacts` bucket의 다음 prefix에 저장한다.

```text
model-artifacts/preference/v1/
standardized/preference/v1/reference_year=2024/
analytics/preference/v1/reference_year=2024/
```

이 단계는 Oracle Database 테이블을 변경하지 않는다. Object Storage 업로드가
완료된 뒤 다음 단계에서 성별×연령별 확률과 격자 잠재수요만 정규화 테이블에
적재하고, 행정동·자치구 결과는 격자 테이블에서 집계해 로컬 CSV와 대조한다.

업로드가 끝나면 다음 순서로 실행한다.

1. `OCI 17 - Load preference outputs to Oracle`
2. `OCI 18 - Verify preference local vs Oracle`

OCI 17은 `FACT_PREF_SEX_AGE` 126행과 `FACT_GRID_PREF_DEMAND` 484,224행을
적재한다. 선호분류는 `PREFERENCE_V1`로 별도 관리하며 정책 8개 분야만
`SUPPLY_MID13`의 같은 분야에 직접 연결한다. `기타·문화누리 비대응`은 공급
분류에 연결하지 않고, 음악·체육용품에는 선호 0을 만들지 않는다.

행정동·자치구 결과를 중복 저장하지 않고 `VW_DONG_PREF_DEMAND`,
`VW_GU_PREF_DEMAND`에서 격자값을 합산한다. OCI 18은 확률 126행, 대표 격자
50개, 행정동 3,408행, 자치구 200행, 전체 총량 보존을 대조하며 다섯 검사가
모두 `passed: true`여야 한다.

## 다섯 번째 데이터 이전: 기존 H3SFCA 결과 그대로 이관

이번 단계는 H3SFCA를 다시 계산하거나 선호확률을 결합하지 않는다. 기존
`notebooks/access/OUTPUT/h3sfca/`의 CSV 5개를 `baseline_v1`으로 그대로
보관하고, 상세 결과만 Oracle 정규화 테이블에 적재한다.

Run and Debug에서 다음 순서로 실행한다.

1. `OCI 19 - Upload existing H3SFCA baseline`
2. `OCI 20 - Load existing H3SFCA baseline to Oracle`
3. `OCI 21 - Verify H3SFCA local vs Oracle`

OCI 19는 다음 기존 파일을 Object Storage에 올린다.

```text
analytics/accessibility/h3sfca/baseline_v1/
├── h3sfca_격자_중분류_접근성.csv       304,509행
├── h3sfca_가맹점_공급수요비.csv          4,282행
├── h3sfca_격자_요약.csv                 94,930행
├── h3sfca_행정동_중분류_요약.csv          3,685행
└── h3sfca_중분류_요약.csv                    10행
```

업로드 전에 현재 격자 결과로 요약 CSV 세 개를 다시 집계해 저장값과 대조한다.
이 검증은 파일을 수정하지 않으며 기존 요약값이 원 격자 결과에서 실제로 나온
값인지 확인한다.

OCI 20은 다음 두 상세 테이블만 적재한다. 이미 저장된 요약 CSV를 중복 테이블로
만들지 않는다.

- `FACT_GRID_ACCESSIBILITY`: 격자×접근수단×중분류 304,509행
- `FACT_FACILITY_ACCESS_RATIO`: 가맹점×접근수단×중분류 4,282행
- `VW_GRID_ACCESSIBILITY`: 최신 성공 실행의 지역명·분류명을 결합한 조회 View

현재 계산 기준은 다음과 같이 고정해 기록한다.

```text
version: baseline_v1
method_code: H3SFCA_GAUSSIAN_HUFF_V1
demand_basis: TARGET_POPULATION_UNWEIGHTED
target_reference_year: 2024
merchant_snapshot_date: 2026-07-06
calculation_changed: false
```

`TARGET_POPULATION_UNWEIGHTED`는 기존 H3SFCA가 격자의 전체 추정 대상자 수를
수요로 사용했다는 뜻이다. 선호확률이나 15세 이상 선호 잠재수요를 새로 넣지
않는다. 따라서 OCI 이전 전후 결과는 같아야 한다.

OCI 21은 격자 304,509행과 가맹점 4,282행을 키별로 전부 대조한다. 접근성값,
접근가능 가맹점 수, 대상자 수, 공급수요비, 자치구·행정동·가맹점명뿐 아니라
Object Storage 원본 5개의 SHA-256도 확인한다. 마지막 출력의 모든 검사에서
`passed: true`와 `all_checks_passed: true`가 나와야 이관 완료다.

주의할 점은 다음과 같다.

- 도보와 대중교통은 같은 중분류를 반복 계산한 것이 아니다. 도보 6개 분야,
  대중교통 4개 분야로 나뉜 기존 구조를 그대로 보존한다.
- 기존 결과에 없는 4,032개 격자를 접근성 0으로 만들지 않는다.
- 이 결과를 `선호확률 반영 접근성`이라고 부르지 않는다.
- 향후 다른 계산을 추가하더라도 `baseline_v1`을 덮어쓰지 않고 별도 버전으로
  관리한다.

## 전체 프로젝트 Oracle 준비상태 확인

H3SFCA 검증까지 끝난 뒤 Run and Debug에서
`OCI 22 - Check full project Oracle readiness`를 실행한다. 이 검사는 대용량
원행을 다시 내려받지 않고 Oracle 내부에서 다음 최신 성공 실행과 행 수를
집계한다.

- 카드 이용실적: 원 27분류, 연도·자치구, 13중분류, 성별, 연령
- 가맹점 snapshot 4,722행
- 격자 대상자 통일연령 1,089,504행과 15세 이상 모델입력 847,392행
- 선호확률 126행과 격자 잠재수요 484,224행
- 기존 H3SFCA 격자 접근성 304,509행과 가맹점 공급수요비 4,282행
- 필수 Oracle 테이블·View 존재 여부
- H3SFCA 수요 기준이 기존 `TARGET_POPULATION_UNWEIGHTED` 한 종류인지

마지막에 `status: project_oracle_ready`와 `all_checks_passed: true`가 나오면
현재 이관 대상 전체가 팀 조회용으로 준비된 것이다.

Python 코드에서는
`src.data_access.accessibility.load_accessibility_data()`를 사용한다.
`backend="local"`은 기존 CSV를, `backend="oracle"`은 최신 성공
`baseline_v1`을 읽어 동일한 한글 컬럼의 DataFrame 두 개를 반환한다. Oracle
모드는 기존 H3SFCA를 다시 계산하지 않는다.

같은 방식으로 다음 두 함수도 사용할 수 있다.

```python
from src.data_access.grid_population import load_grid_model_input
from src.data_access.preference import load_preference_data

# 기존 로컬 파일을 그대로 읽기
grid_input = load_grid_model_input(backend="local", project_root=PROJECT_ROOT)
preference_probability, grid_demand = load_preference_data(
    backend="local",
    project_root=PROJECT_ROOT,
)

# Oracle을 사용할 때는 검증된 MNCDEV connection을 전달
grid_input = load_grid_model_input(
    backend="oracle",
    project_root=PROJECT_ROOT,
    oracle_connection=connection,
)
preference_probability, grid_demand = load_preference_data(
    backend="oracle",
    project_root=PROJECT_ROOT,
    oracle_connection=connection,
)
```

두 backend의 반환 컬럼은 동일하다. `local`은 기존 CSV를 읽고 `oracle`은 같은
결과의 최신 성공 ETL을 조회한다. 조회 함수는 모델을 다시 학습하거나 격자
잠재수요·H3SFCA를 다시 계산하지 않는다.

## GitHub에 올리지 않는 파일

- `.env.oci.local`
- Wallet ZIP과 Wallet 내부 인증서·키 파일
- DB·Wallet 비밀번호
- `.oci_*_local.json` 실행 영수증
- `data/raw/`, `data/processed/`의 실제 데이터와 생성 결과

GitHub에는 코드, 테스트, 비밀값이 없는 설정 예시와 문서만 올린다.
