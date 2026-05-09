from __future__ import annotations

import argparse
import logging

from services.analysis_worker import run_worker


def main() -> None:
    parser = argparse.ArgumentParser(description="YC AIxBio analysis queue worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued job and exit.",
    )
    parser.add_argument(
        "--worker-name",
        type=str,
        default=None,
        help="Optional worker identity label included in job events.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    run_worker(worker_name=args.worker_name, process_once=args.once)


if __name__ == "__main__":
    main()
