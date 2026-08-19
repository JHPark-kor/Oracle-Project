# Oracle MNC Project

문화누리카드(MNC) 이용, 가맹점, 인구통계, 선호도, 교통, 공간 데이터를 연결해 서울 지역 문화복지 접근성과 정책 개선 지점을 분석하는 협업 프로젝트입니다.

이 저장소의 `main` 브랜치는 팀원들이 공통으로 받아가는 기준 구조입니다. 실제 데이터와 개인 실험 결과물은 각자 로컬 환경 또는 개인 브랜치에서 관리합니다.

## Project Goals

- 서울시 문화누리카드 이용 및 발급 데이터를 지역 단위로 정리합니다.
- 오프라인 가맹점, 후보 가맹점, 교통, 공간 데이터를 결합해 접근성 지표를 설계합니다.
- 고령자, 장애인, 기초생활수급자 등 정책 대상자 분포와 문화 소비 여건을 함께 해석합니다.
- EDA와 검증 분석을 통해 정책적으로 설명 가능한 인사이트를 도출합니다.

## Project Roadmap

```mermaid
flowchart LR
    A["정책 목적 정의<br/>문화권, 문화격차, 현행 검토"] --> B["EDA<br/>이용 현황, 접근성, 격차 점검"]
    B --> C["접근성 고도화<br/>OSM 네트워크, 일반 시민 대비 비교"]
    C --> D["모델링<br/>지역·인구 특성별 선호 예측"]
    D --> E["지표 고도화<br/>선호·이동취약성 가중 접근성"]
    E --> F["정책·서비스 방향<br/>우선지역, 대시보드, 앱 기획"]
    F --> G["최종 산출물<br/>분석 노트북, 시각화, 발표자료"]

    classDef done fill:#e9f7ef,stroke:#2f9d63,color:#173f2a;
    classDef current fill:#fff4db,stroke:#d68a00,color:#4a3100;
    classDef next fill:#eaf2ff,stroke:#3974d8,color:#19375f;
    classDef future fill:#f4f4f5,stroke:#9ca3af,color:#374151;

    class A,B done;
    class C current;
    class D,E next;
    class F,G future;
```

자세한 진행 단계와 세부 태스크를 알고 싶다면? [인터랙티브 마일스톤 보기](https://jhpark-kor.github.io/Oracle-Project/)

## This Week Board

> [!NOTE]
> 금요일 회의 전까지 EDA 기준을 맞추고, 접근성 고도화·모델링·서비스 방향을 다음 단계로 넘길 준비를 합니다.

### Friday Agenda

- **EDA 최종 정리**: 문제 정의, 주요 결과, 핵심 시각화, 전처리·지표 계산식, 가정과 한계
- **접근성 기준 결정**: 도보·대중교통 생활권, 평균 이동속도, 양호·보통·취약 라벨링
- **대시보드·앱 방향 논의**: 핵심 사용자, 기능, 지도·필터·시뮬레이션, 분석 결과 연결 방식
- **역할 배분**: 분석 테이블, EDA 보고서, 모델링, 접근성·취약지표 설계

> [!IMPORTANT]
> 연도 기준과 컬럼명을 통일한 뒤, 데이터만 교체해서 다시 실행할 수 있게 정리합니다.

### Required By Friday

- [ ] **접근성 기준 근거 조사**: 접근시간, 평균 이동속도, 정부 보고서·논문·정책 사례
- [ ] **각자 EDA 방식 정리**: 데이터·기간·분석 단위, 전처리·결합 방식, 알고리즘·계산식·파생변수
- [ ] **필요 데이터 정리**: 부족 데이터, 대체 가능 데이터, 추가 확보 경로

### If Time Allows

- 모델링 설계 아이디어: 목적, 목표변수, 설명변수, 분석 단위, 특성공학, 모델 후보, 평가 방법
- 상대적 접근성 평가 방식: 서울 시민 접근성이 과소평가되지 않는 비교 피쳐와 비교 방식
- 취약지수 고도화: 표준화, 가중치, 종합 취약지수, 정책 우선지역 선정 기준

### Mentor Feedback

- 연도별 데이터 기준 컬럼 통일
- SMART 기반 문제 정의 구체화
- 프로젝트 비전이 드러나는 서비스명 결정

## Repository Structure

```text
oracle_mnc_project/
├── data/
│   ├── raw/                 # local raw data placeholders only
│   ├── interim/             # intermediate datasets, local only
│   └── processed/           # processed datasets, local only
├── docs/
│   ├── index.html           # GitHub Pages interactive roadmap
│   ├── folder_guide.md      # folder usage guide
│   ├── team_setup_guide.md  # collaborator setup guide
│   └── references/          # reference notes, not raw PDF storage
├── metadata/
│   └── data_metadata.md     # source data catalog
├── models/                  # reviewed lightweight model handoff bundles
├── notebooks/
│   ├── exploratory_eda/     # individual/team EDA notebooks
│   └── policy_validation_eda/
├── src/                     # reusable analysis code
├── requirements.txt
└── README.md
```

## Data Policy

Raw data, processed data, downloaded archives, and report PDFs are not tracked in Git. The repository keeps only the folder structure and metadata so every member can place the same local files in the same paths.

- Keep local data under `data/raw/`.
- Keep intermediate or generated datasets under `data/interim/` or `data/processed/`.
- Keep bulky reference PDFs locally or in shared storage. GitHub should contain only lightweight notes and guides.
- Do not commit `.env`, cache files, notebook checkpoints, ad-hoc model files, or temporary
  outputs. An explicitly reviewed lightweight bundle under `models/` may be tracked only when
  it contains no row-level source data and includes its input contract, class order, versions,
  checksum, and usage guide.

## Collaboration Workflow

1. Start from the latest `main` branch.
2. Create a personal branch such as `feature/pjh-eda`, `feature/JHB-eda`, or `feature/CYS-modeling`.
3. Work in your own branch and commit only files that belong to the project.
4. Open a Pull Request back into `main` after the notebook, code, or documentation is ready to share.
5. Keep data files local; use `metadata/data_metadata.md` to confirm expected file paths.

## Getting Started

```powershell
git clone https://github.com/JHPark-kor/Oracle-Project.git
cd Oracle-Project
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

After cloning, place the shared data files under the paths described in [`metadata/data_metadata.md`](metadata/data_metadata.md).

## Key Documents

- [`docs/oci_quickstart.md`](docs/oci_quickstart.md): OCI MNCDEV·Wallet·VS Code 연결 빠른 사용법
- [`metadata/data_metadata.md`](metadata/data_metadata.md): source data path and description
- [`docs/preference_analysis.md`](docs/preference_analysis.md): 만족활동 기반 선호예측·공간 적용 실행 및 해석
- [`models/preference_analysis/v1/README.md`](models/preference_analysis/v1/README.md): 팀 전달용 선호모델·H3SFCA 결합 계약
- [`docs/folder_guide.md`](docs/folder_guide.md): folder-by-folder usage rules
- [`docs/team_setup_guide.md`](docs/team_setup_guide.md): clone, branch, commit, and PR workflow
