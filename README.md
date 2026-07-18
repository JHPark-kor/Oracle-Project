# Oracle MNC Project

문화누리카드(MNC) 이용, 가맹점, 인구통계, 선호도, 교통, 공간 데이터를 연결해 서울 지역 문화복지 접근성과 정책 개선 지점을 분석하는 협업 프로젝트입니다.

이 저장소의 `main` 브랜치는 팀원들이 공통으로 받아가는 기준 구조입니다. 실제 데이터와 개인 실험 결과물은 각자 로컬 환경 또는 개인 브랜치에서 관리합니다.

## Project Goals

- 서울시 문화누리카드 이용 및 발급 데이터를 지역 단위로 정리합니다.
- 오프라인 가맹점, 후보 가맹점, 교통, 공간 데이터를 결합해 접근성 지표를 설계합니다.
- 고령자, 장애인, 기초생활수급자 등 정책 대상자 분포와 문화 소비 여건을 함께 해석합니다.
- EDA와 검증 분석을 통해 정책적으로 설명 가능한 인사이트를 도출합니다.

## Repository Structure

```text
oracle_mnc_project/
├── data/
│   ├── raw/                 # local raw data placeholders only
│   ├── interim/             # intermediate datasets, local only
│   └── processed/           # processed datasets, local only
├── docs/
│   ├── folder_guide.md      # folder usage guide
│   ├── team_setup_guide.md  # collaborator setup guide
│   └── references/          # reference notes, not raw PDF storage
├── metadata/
│   └── data_metadata.md     # source data catalog
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
- Do not commit `.env`, cache files, notebook checkpoints, model files, or temporary outputs.

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

- [`metadata/data_metadata.md`](metadata/data_metadata.md): source data path and description
- [`docs/folder_guide.md`](docs/folder_guide.md): folder-by-folder usage rules
- [`docs/team_setup_guide.md`](docs/team_setup_guide.md): clone, branch, commit, and PR workflow
