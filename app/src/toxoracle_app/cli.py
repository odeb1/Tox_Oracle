"""Command-line entry point for the offline ToxOracle integration path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .join import combine_responses
from .validation import ContractValidationError


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(document, file, indent=2, ensure_ascii=False)
        file.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and combine ToxOracle discovery and toxicity responses."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    combine = subparsers.add_parser("combine", help="Combine two v2 response files.")
    combine.add_argument("--request", required=True, type=Path)
    combine.add_argument("--discovery", required=True, type=Path)
    combine.add_argument("--toxicity", required=True, type=Path)
    combine.add_argument("--config", required=True, type=Path)
    combine.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        combined = combine_responses(
            _load_json(args.request),
            _load_json(args.discovery),
            _load_json(args.toxicity),
            _load_json(args.config),
        )
        _write_json(args.output, combined)
    except (ContractValidationError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}")
        return 1

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
