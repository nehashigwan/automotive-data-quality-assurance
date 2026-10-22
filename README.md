# Automotive Data Quality Assurance — Week 2
## Automated Data Validation Pipeline

This repository extends the Week 1 automotive data collection strategy with a runnable, rule-based validation pipeline. The default run uses synthetic sample records with deliberate quality issues and works offline.

## Features
- Schema and required-column checks
- Completeness / null-rate checks
- Numeric type coercion and domain range checks
- VIN format validation (17 characters; excludes I, O, Q)
- Duplicate natural-key detection (`make + model + year`)
- Text consistency checks for make names
- Profiling report, validation report, run summary
- Row-level quarantine for failed records
- Logging to console and `logs/validation_pipeline.log`
- Immutable-ish raw snapshot retained separately from staged output

## Setup
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the offline demonstration
```bash
python src/validation_pipeline.py
```

## Validate your own CSV
The CSV should include `make`, `model`, `year`, `comb_mpg`, and `displacement_l`.
```bash
python src/validation_pipeline.py --input data/raw/my_vehicles.csv --name my_vehicles
```

## Output folders
- `data/raw/`: raw input snapshot; never cleaned in place
- `data/staged/`: accepted and standardised records
- `data/quarantine/`: rows that need review
- `reports/`: column profile, rule results, and run summary CSVs
- `logs/`: execution log

## Important interpretation notes
- A failed check is a review flag, not automatically proof that the source value is false.
- Thresholds in `src/validation_pipeline.py` are examples and should be adapted to each source's schema and domain.
- The pipeline quarantines rows if any row-level rule fails; dataset-level rule failures are reported separately.
- This educational pipeline does not prove real-world accuracy by itself. Cross-source reconciliation (for example, comparing vehicle details against NHTSA or FuelEconomy.gov) is a planned next step.
- Review source licences, API terms, and privacy requirements before collecting or redistributing real data.
