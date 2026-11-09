"""Run the whole EVISION 360 pipeline from raw files to the PostgreSQL warehouse.

Usage (from the repo root, with the .venv active):
    python run_pipeline.py              # mapping -> cleaning -> warehouse load -> analytics load
    python run_pipeline.py --skip-db    # stop after the cleaning steps (no PostgreSQL needed)
    python run_pipeline.py --test       # also run the test suite at the end

Each step is an ordinary script, so any step can still be run on its own.
The analytics step loads CSV files written by notebooks 06, 07 and 07b (skipped with a message if a file is missing).
Stops at the first failing step.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STEPS = [
    ("Country mapping (name -> ISO3)", "src/transformation/build_country_mapping.py", False),
    ("Clean Ember monthly sales", "src/cleaning/clean_ember.py", False),
    ("Clean IEA Global EV Data", "src/cleaning/clean_iea.py", False),
    ("Clean World Bank indicators", "src/cleaning/clean_worldbank.py", False),
    ("Load PostgreSQL warehouse", "src/transformation/load_warehouse.py", True),  # True = needs the database
    ("Load analytics outputs (segments, forecasts, readiness)", "src/transformation/load_analytics.py", True),
]


def run_step(number: int, total: int, title: str, script: str) -> float:
    print(f"\n=== [{number}/{total}] {title} ===", flush=True)
    start = time.time()
    result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"\nStep failed: {title} ({script}). Fix the error above and run again.")
    return time.time() - start


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the EVISION 360 data pipeline.")
    parser.add_argument("--skip-db", action="store_true", help="skip the PostgreSQL load step")
    parser.add_argument("--test", action="store_true", help="run pytest after the pipeline")
    args = parser.parse_args()

    steps = [s for s in STEPS if not (args.skip_db and s[2])]
    timings = []
    for i, (title, script, _) in enumerate(steps, start=1):
        timings.append((title, run_step(i, len(steps), title, script)))

    if args.test:
        print("\n=== Tests ===", flush=True)
        if subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=ROOT).returncode != 0:
            sys.exit("\nTests failed.")

    print("\nPipeline finished:")
    for title, seconds in timings:
        print(f"  {seconds:6.1f}s  {title}")


if __name__ == "__main__":
    main()
