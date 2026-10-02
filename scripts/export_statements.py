"""Export a PDF tree with source filenames, rewards sidecars, and a validation manifest."""

# ruff: noqa: INP001 - standalone command-line script

import json
from dataclasses import asdict
from pathlib import Path

import click

from monopoly.banks import BankDetector, banks
from monopoly.pdf import PdfDocument, PdfParser
from monopoly.pipeline import Pipeline


def export_one(source: Path, destination: Path) -> dict:
    with PdfDocument(source) as document:
        document.unlock_document()
        bank = BankDetector(document).detect_bank(banks)
        if bank is None:
            msg = "Bank not detected"
            raise ValueError(msg)
        pipeline = Pipeline(PdfParser(bank, document))
        statement = pipeline.extract()
        transactions = pipeline.transform(statement)
        destination.mkdir(parents=True, exist_ok=True)
        pipeline.load(transactions, statement, destination, preserve_filename=True)
        summary = statement.points_summary
        return {
            "type": str(statement.statement_type),
            "period_start": statement.period_start.date().isoformat() if statement.period_start else None,
            "period_end": statement.statement_date.date().isoformat(),
            "account": statement.account,
            "transactions": len(transactions),
            "points": asdict(summary) if summary else None,
        }


@click.command()
@click.argument("source", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("output", type=click.Path(file_okay=False, path_type=Path))
def main(source: Path, output: Path) -> None:
    """Export all statements in SOURCE into OUTPUT, preserving the directory tree."""
    results = []
    failures = 0
    for pdf in sorted(source.rglob("*.pdf")):
        relative = pdf.relative_to(source)
        try:
            result = export_one(pdf, output / relative.parent)
            if result["points"] and result["points"]["reconciliation_difference"] not in (0, None):
                failures += 1
                result["error"] = "Points do not reconcile; see reconciliation_difference"
        except Exception as error:  # noqa: BLE001 - report every file, then fail the batch
            failures += 1
            result = {"error": f"{type(error).__name__}: {error}"}
        results.append({"file": str(relative), **result})
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf8")
    click.echo(f"Processed {len(results)} PDFs; {failures} failed validation")
    if failures:
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    main()
