# Team Setup Guide

팀원이 `Oracle-Project` 저장소를 처음 받을 때 사용하는 안내서입니다.

## 1. Clone

```powershell
git clone https://github.com/JHPark-kor/Oracle-Project.git
cd Oracle-Project
```

## 2. Python Environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Data Placement

실제 데이터는 GitHub에 올라가지 않습니다. 공유받은 데이터 파일을 `metadata/data_metadata.md`에 적힌 경로와 같은 위치에 넣습니다.

예시:

```text
data/raw/mnc_card/mnc_seoul_usage_issuance_2021_2025.xlsx
data/raw/merchants/source/mnc_seoul_offline_merchants_20260706.xlsx
data/raw/transport/bus_stations/source/seoul_bus_stations.csv
```

## 4. Branch Workflow

개인 작업은 반드시 본인 브랜치에서 진행합니다.

```powershell
git checkout main
git pull origin main
git checkout -b feature/본인이름-작업명
```

예시:

```powershell
git checkout -b feature/jaesung-eda
git checkout -b feature/jiyoon-modeling
```

## 5. Commit and Push

```powershell
git status
git add <changed-files>
git commit -m "Add initial EDA notebook"
git push -u origin HEAD
```

GitHub에서 Pull Request를 만들어 `main`으로 병합합니다.

## 6. Do Not Commit

- `data/raw/`, `data/interim/`, `data/processed/`의 실제 데이터 파일
- `.env`, `.venv/`, `__pycache__/`, `.ipynb_checkpoints/`
- 임시 테스트 notebook과 개인 출력 파일
- 용량이 큰 PDF, zip, model, output 파일
