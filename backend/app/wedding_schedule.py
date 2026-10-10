"""Independent, idempotent wedding invoice sender.

uv run python -m app.wedding_schedule          # report due invoices
uv run python -m app.wedding_schedule --apply  # send approved, due invoices
"""

import argparse
import asyncio
import sys

from .weddings import run_wedding_schedule


def main():
    """Report or send due wedding invoices from the command line."""
    parser = argparse.ArgumentParser(description="Send approved wedding invoices on their selected Eastern dates")
    parser.add_argument("--apply", action="store_true", help="send due invoices through Stripe")
    args = parser.parse_args()
    findings = asyncio.run(run_wedding_schedule(apply=args.apply))
    for finding in findings:
        print(finding)
    if any("needs review" in finding for finding in findings):
        sys.exit(1)
    if not findings:
        print("No wedding invoices due to send.")


if __name__ == "__main__":
    main()
