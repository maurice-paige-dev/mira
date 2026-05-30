#!/usr/bin/env python3
"""
CLI entry point for the MLOps data-conversion pipeline.

Usage:
  # Auto-detect next file in data/ingest/ and run with target 'inventory'
  python run_pipeline.py

  # Run on a specific file
  python run_pipeline.py --file data/ingest/new_products.json

  # Target a different schema (inventory_category, purchase_order, invoice, shipping_order)
  python run_pipeline.py --file data/ingest/new_products.json --target purchase_order

  # Dry-run (validate without writing)
  python run_pipeline.py --file data/ingest/new_products.json --dry-run

  # Process all pending files
  python run_pipeline.py --all

  # Skip RAG rebuild (just append to CSV)
  python run_pipeline.py --file data/ingest/new_products.json --no-rag
"""

import argparse
import sys
from pathlib import Path

from backend.orchestrator import run_pipeline, run_all

TARGETS = ["inventory", "inventory_category", "purchase_order", "invoice", "shipping_order"]


def main():
    parser = argparse.ArgumentParser(
        description="MLOps data conversion pipeline \u2014 ingest, transform, validate, integrate."
    )
    parser.add_argument(
        "--file", "-f", type=str, default=None,
        help="Path to the input file in data/ingest/ (default: auto-discover next file)",
    )
    parser.add_argument(
        "--target", "-t", type=str, default="inventory", choices=TARGETS,
        help="Target schema to transform into (default: inventory)",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Run validation only; do not write to CSV or rebuild RAG",
    )
    parser.add_argument(
        "--no-rag", action="store_true",
        help="Skip RAG vector store rebuild after integration",
    )
    parser.add_argument(
        "--all", "-a", action="store_true",
        help="Process all pending files in data/ingest/",
    )
    args = parser.parse_args()

    if args.dry_run and args.no_rag:
        # --no-rag is irrelevant in dry-run mode, but don't error
        pass

    if args.all:
        reports = run_all(rebuild_rag=not args.no_rag, dry_run=args.dry_run)
        if not reports:
            sys.exit(0)
        failed = sum(1 for r in reports if not r.get("passed"))
        sys.exit(failed)

    file_path = Path(args.file) if args.file else None
    report = run_pipeline(
        file_path=file_path,
        target=args.target,
        rebuild_rag=not args.no_rag,
        dry_run=args.dry_run,
    )

    if not report.get("passed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
