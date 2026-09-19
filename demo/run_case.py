"""Validate and render one cached or live ToxOracle demo case."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator

from toxoracle_app.join import combine_responses
from toxoracle_app.report import render_combined_report


DEMO_DIR = Path(__file__).resolve().parent
CASE_SCHEMA_PATH = DEMO_DIR / "case.schema.json"


class DemoCaseError(ValueError):
    """Raised when a demo case is incomplete, unsafe, or incorrectly labelled."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(document, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _case_file(case_dir: Path, relative_path: str) -> Path:
    root = case_dir.resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise DemoCaseError(f"case file escapes the case directory: {relative_path}")
    if not path.is_file():
        raise DemoCaseError(f"case file does not exist: {relative_path}")
    return path


def _validate_manifest(manifest: dict[str, Any]) -> None:
    validator = Draft202012Validator(_load_json(CASE_SCHEMA_PATH))
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.path))
    if errors:
        messages = [f"{'.'.join(map(str, error.path)) or '$'}: {error.message}" for error in errors]
        raise DemoCaseError("; ".join(messages))


def run_case(
    case_dir: Path,
    config_path: Path,
    output_dir: Path,
    *,
    allow_interface_fixture: bool = False,
) -> dict[str, Path]:
    """Validate a case manifest, combine its inputs, and write reproducible outputs."""

    case_dir = case_dir.resolve()
    manifest_path = case_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    _validate_manifest(manifest)

    if manifest["status"] != "ready":
        raise DemoCaseError("demo case is not marked ready")
    if manifest["result_class"] == "interface_fixture" and not allow_interface_fixture:
        raise DemoCaseError(
            "interface fixtures are not permitted as final demo cases; "
            "use --allow-interface-fixture only for a dry run"
        )

    input_paths = {
        "request": _case_file(case_dir, manifest["request_file"]),
        "discovery_response": _case_file(
            case_dir, manifest["discovery_response_file"]
        ),
        "toxicity_response": _case_file(
            case_dir, manifest["toxicity_response_file"]
        ),
        "policy": config_path.resolve(),
    }
    if not input_paths["policy"].is_file():
        raise DemoCaseError(f"policy file does not exist: {config_path}")

    combined = combine_responses(
        _load_json(input_paths["request"]),
        _load_json(input_paths["discovery_response"]),
        _load_json(input_paths["toxicity_response"]),
        _load_json(input_paths["policy"]),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    json_output = output_dir / "combined-report.json"
    html_output = output_dir / "combined-report.html"
    metadata_output = output_dir / "run-metadata.json"
    _write_json(json_output, combined)
    html_output.write_text(render_combined_report(combined), encoding="utf-8")
    _write_json(
        metadata_output,
        {
            "case_id": manifest["case_id"],
            "execution_mode": manifest["execution_mode"],
            "result_class": manifest["result_class"],
            "training_membership": manifest["training_membership"],
            "inputs": {
                name: {"path": str(path), "sha256": _sha256(path)}
                for name, path in input_paths.items()
            },
            "outputs": {
                "combined_report_json": {
                    "path": str(json_output),
                    "sha256": _sha256(json_output),
                },
                "combined_report_html": {
                    "path": str(html_output),
                    "sha256": _sha256(html_output),
                },
            },
            "tool_versions": manifest["tool_versions"],
            "provenance_refs": manifest["provenance_refs"],
            "limitations": manifest["limitations"],
        },
    )
    return {
        "json": json_output,
        "html": html_output,
        "metadata": metadata_output,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--allow-interface-fixture", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outputs = run_case(
            args.case_dir,
            args.config,
            args.output_dir,
            allow_interface_fixture=args.allow_interface_fixture,
        )
    except (DemoCaseError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}")
        return 1
    for name, path in outputs.items():
        print(f"Wrote {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
