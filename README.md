# Automotive Data Quality Assurance

Python project for collecting, profiling, validating and cleaning public automotive datasets.
It accompanies the *Data Collection Strategy Report* (Week 1).

## What it does
1. **Ingest**: downloads data from public sources and stores it unchanged in `data/raw/` with a manifest (URL, timestamp, row count, SHA-256 checksum).
   - NHTSA vPIC API (VIN decoding), using `requests` with retries
   - FuelEconomy.gov bulk CSV (EPA/DOE), using `pandas`
   - Optional HTML table scraper (`BeautifulSoup`) that checks `robots.txt` first
2. **Profile**: column types, null rates and distinct counts.
3. **Validate**: rule-based checks for completeness, validity, accuracy ranges, uniqueness, consistency and timeliness.
4. **Report**: CSV quality reports in `reports/` and cleaned data in `data/staged/`.

## Setup
```
pip install -r requirements.txt
```

## Usage
```
python automotive_data_collection.py --demo          # offline demo with built-in sample data
python automotive_data_collection.py --fueleconomy   # download and check FuelEconomy.gov data
python automotive_data_collection.py --vin 1HGCM82633A004352
python automotive_data_collection.py --all
```

## Project layout
```
automotive_data_collection.py   main script
requirements.txt
data/raw/      unchanged downloads + manifest.jsonl
data/staged/   cleaned data
reports/       profile and validation CSVs
logs/          run logs
```

## Data sources and licences
Check each publisher's terms of use before reusing data. Sources are listed in the report (NHTSA, EPA/DOE FuelEconomy.gov, UCI, EEA, Open Charge Map, Vahan/data.gov.in, Kaggle).

## Author
Neha
