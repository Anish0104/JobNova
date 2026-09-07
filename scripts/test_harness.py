"""Run resolve_job_listing_url over a list of LinkedIn job URLs and log results to CSV.

Usage:
    python scripts/test_harness.py
    python scripts/test_harness.py --input data/test_urls.txt --output data/results.csv --headed
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Explicit path, not dotenv's default stack-walking search: this makes
# .env loading independent of the CWD the script is invoked from.
load_dotenv(REPO_ROOT / ".env")

sys.path.insert(0, str(REPO_ROOT))

from job_agent.pipeline import resolve_job_listing_url

DEFAULT_INPUT = REPO_ROOT / "data" / "test_urls.txt"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "results.csv"


def load_urls(path: Path) -> list[str]:
    urls = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def run(input_path: Path, output_path: Path, headless: bool) -> pd.DataFrame:
    urls = load_urls(input_path)
    rows = []
    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] {url}")
        result = resolve_job_listing_url(url, headless=headless)
        print(f"  -> {result['status']}: {result['reason']}")
        rows.append(result)

    df = pd.DataFrame(rows)
    # "stages" is a nested list (per-stage timing/status) — useful in-process,
    # but not worth flattening into the summary CSV.
    df.drop(columns=["stages"], errors="ignore").to_csv(output_path, index=False)
    return df


def print_summary(df: pd.DataFrame) -> None:
    total = len(df)
    successes = int((df["status"] == "success").sum())
    rate = (successes / total * 100) if total else 0.0

    print("\n=== Summary ===")
    print(f"Total: {total}  Success: {successes}  Failed: {total - successes}  Success rate: {rate:.1f}%")

    failures = df[df["status"] != "success"]
    if not failures.empty:
        print("\nFailures:")
        for _, row in failures.iterrows():
            print(f"  - {row['linkedin_job_url']}: {row['reason']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to a file with one LinkedIn job URL per line")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the results CSV")
    parser.add_argument("--headed", action="store_true", help="Run the browser with a visible window (default: headless)")
    args = parser.parse_args()

    df = run(args.input, args.output, headless=not args.headed)
    print_summary(df)
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
