"""Command-line interface for the finance insights engine."""

import argparse
import sys

from .engine import analyze


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a bank or credit-card transaction CSV.")
    parser.add_argument("csv", help="Path to the transaction CSV")
    parser.add_argument("--out", default="finance_output", help="Output directory (default: finance_output)")
    parser.add_argument("--dayfirst", action="store_true", help="Parse ambiguous dates as DD/MM/YYYY")
    args = parser.parse_args()
    try:
        results = analyze(args.csv, args.out, dayfirst=args.dayfirst)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print("Analysis complete. Files written:")
    for name, path in results.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
