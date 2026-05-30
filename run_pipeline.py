#!/usr/bin/env python3
"""
CLI entry point for the MLOps data-conversion pipeline.

Usage:
  # ── One-shot ────────────────────────────────────────────
  python run_pipeline.py                        # auto-discover next file
  python run_pipeline.py --file data/ingest/new_products.json
  python run_pipeline.py --file my_data.csv --target purchase_order
  python run_pipeline.py --all --dry-run        # validate without writing
  python run_pipeline.py --file bad.csv --no-rag

  # ── Watch mode ──────────────────────────────────────────
  python run_pipeline.py --watch                # poll forever
  python run_pipeline.py --watch --watch-once   # process pending & exit
  python run_pipeline.py --watch --interval 10  # custom poll interval
  nohup python run_pipeline.py --watch &        # background daemon
"""

import argparse
import sys
from pathlib import Path

from backend.orchestrator import run_pipeline, run_all
from backend.watcher import watch, run_once as watch_once

TARGETS = ["inventory", "inventory_category", "purchase_order", "invoice", "shipping_order"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="MLOps data conversion pipeline \u2014 ingest, transform, validate, integrate."
    )

    # ── operation mode ──
    mode = parser.add_argument_group("operation mode (mutually exclusive)")
    mode.add_argument("--file", "-f", type=str, default=None,
                      help="Process a specific file")
    mode.add_argument("--all", "-a", action="store_true",
                      help="Process all pending files and exit")
    mode.add_argument("--watch", "-w", action="store_true",
                      help="Watch data/ingest/ for new files and process automatically")

    # ─── watch options ──
    watch_opts = parser.add_argument_group("watch-mode options")
    watch_opts.add_argument("--watch-once", action="store_true",
                            help="In watch mode: process current files then exit")
    watch_opts.add_argument("--interval", type=int, default=5,
                            help="Poll interval in seconds (default: 5)")

    # ── pipeline options ──
    pipeline = parser.add_argument_group("pipeline options")
    pipeline.add_argument("--target", "-t", type=str, default="inventory", choices=TARGETS,
                          help="Target schema (default: inventory)")
    pipeline.add_argument("--dry-run", "-n", action="store_true",
                          help="Validate only; do not write to CSV or rebuild RAG")
    pipeline.add_argument("--no-rag", action="store_true",
                          help="Skip RAG vector store rebuild after integration")
    return parser.parse_args(argv)


def main():
    args = parse_args()

    # ── Watch mode ──────────────────────────────────────────
    if args.watch:
        import backend.watcher as watcher
        watcher.POLL_INTERVAL = max(args.interval, 1)
        if args.watch_once:
            result = watch_once(rebuild_rag=not args.no_rag)
            sys.exit(0 if all(r["passed"] for r in result) else 1)
        else:
            watch(rebuild_rag=not args.no_rag)
            sys.exit(0)

    # ── One-shot modes ──────────────────────────────────────
    if args.all:
        reports = run_all(rebuild_rag=not args.no_rag, dry_run=args.dry_run)
        if not reports:
            sys.exit(0)
        failed = sum(1 for r in reports if not r.get("passed"))
        sys.exit(failed)

    file_path = Path(args.file) if args.file else None

    if not args.dry_run and args.target != "inventory":
        # Only one target at a time when not using --all
        pass

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
