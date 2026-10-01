import json
import os
import re
from pathlib import Path
import pytest
from click.testing import CliRunner
from monopoly.cli.models import Report, Result
from monopoly.cli import (
    get_statement_paths,
    monopoly,
    pprint_transactions,
)
from monopoly.statements.transaction import Transaction


@pytest.fixture
def mock_results():
    result1 = Result(source_file_name="statement1.pdf", target_file_name="processed1.csv")
    result2 = Result(
        source_file_name="statement2.pdf",
        error_info={
            "message": "Error",
            "traceback": "Traceback (most recent call last)",
        },
    )
    return [result1, result2]


@pytest.fixture
def test_directory() -> Path:
    return Path("tests/integration/test_cli").resolve()


@pytest.fixture
def cli_runner():
    yield CliRunner()


def test_display_report(mock_results, capsys):
    report = Report(results=mock_results)
    report.display_report()
    captured = capsys.readouterr()
    printed_output = captured.out.strip().split("\n")
    assert "1 statement(s) had errors while processing" in printed_output
    assert "1 statement(s) processed" in printed_output
    assert "statement1.pdf -> processed1.csv" in printed_output
    assert "statement2.pdf -- Error" in printed_output

    # Test verbose output
    report.display_report(verbose=True)
    captured = capsys.readouterr()
    printed_output = captured.out.strip().split("\n")
    assert "statement2.pdf -- Traceback (most recent call last)" in printed_output


def test_help_command(cli_runner: CliRunner) -> None:
    help_results = cli_runner.invoke(monopoly, args="--help")
    assert help_results.exit_code == 0
    assert help_results.stdout.startswith("Usage: monopoly")


def test_monopoly_output(cli_runner: CliRunner, tmp_path: Path):
    output_dir = tmp_path / "results"
    output_dir.mkdir()

    # Pass the PDF path from the fixture and the temporary output directory
    result = cli_runner.invoke(monopoly, ["src/monopoly/examples/example_statement.pdf", "--output", str(output_dir)])

    assert result.exit_code == 0
    assert "1 statement(s) processed" in result.output

    # Check that a CSV output file was created
    csv_files = [f for f in os.listdir(output_dir) if f.endswith(".csv")]
    assert len(csv_files) == 1, f"Expected exactly one CSV file, found {len(csv_files)}"
    assert csv_files[0] in result.output


def test_monopoly_output_json(cli_runner: CliRunner, tmp_path: Path):
    output_dir = tmp_path / "results"
    output_dir.mkdir()

    result = cli_runner.invoke(
        monopoly,
        ["src/monopoly/examples/example_statement.pdf", "--output", str(output_dir), "--format", "json"],
    )

    assert result.exit_code == 0
    assert "1 statement(s) processed" in result.output

    # exactly one .json and no .csv written
    json_files = [f for f in os.listdir(output_dir) if f.endswith(".json")]
    assert len(json_files) == 1, f"Expected exactly one JSON file, found {len(json_files)}"
    assert json_files[0] in result.output
    assert not [f for f in os.listdir(output_dir) if f.endswith(".csv")]

    data = json.loads((output_dir / json_files[0]).read_text())
    assert data["schema_version"] == 2
    assert data["transactions"]
    assert data["transactions"][0]["id"]

    # the example statement's previous-balance line is routed into `balances`,
    # not `transactions`
    assert len(data["balances"]) == 1
    assert data["balances"][0]["type"] == "previous"
    assert not any("PREVIOUS BALANCE" in t["description"].upper() for t in data["transactions"])


def test_monopoly_output_csv_explicit(cli_runner: CliRunner, tmp_path: Path):
    # --format csv is the default behaviour: one .csv, no .json
    output_dir = tmp_path / "results"
    output_dir.mkdir()

    result = cli_runner.invoke(
        monopoly,
        ["src/monopoly/examples/example_statement.pdf", "--output", str(output_dir), "--format", "csv"],
    )

    assert result.exit_code == 0
    csv_files = [f for f in os.listdir(output_dir) if f.endswith(".csv")]
    assert len(csv_files) == 1
    assert not [f for f in os.listdir(output_dir) if f.endswith(".json")]


def test_monopoly_output_preserve_filename(cli_runner: CliRunner, tmp_path: Path):
    output_dir = tmp_path / "results"
    output_dir.mkdir()

    result = cli_runner.invoke(
        monopoly,
        [
            "src/monopoly/examples/example_statement.pdf",
            "--output",
            str(output_dir),
            "--preserve-filename",
        ],
    )

    assert result.exit_code == 0
    assert "1 statement(s) processed" in result.output

    expected_csv_path = output_dir / "example_statement.csv"
    assert expected_csv_path.exists()
    assert str(expected_csv_path.name) in result.output


def test_monopoly_preserve_filename_without_output(cli_runner: CliRunner):
    with cli_runner.isolated_filesystem():
        repo_root = Path(__file__).resolve().parents[2]
        src_pdf = repo_root / "src/monopoly/examples/example_statement.pdf"
        Path("example_statement.pdf").write_bytes(src_pdf.read_bytes())

        result = cli_runner.invoke(
            monopoly,
            [
                "example_statement.pdf",
                "--preserve-filename",
            ],
        )

        assert result.exit_code == 0
        expected_csv_path = Path("example_statement.csv")
        assert expected_csv_path.exists()
        assert str(expected_csv_path.name) in result.output


def test_monopoly_pprint(cli_runner: CliRunner):
    result = cli_runner.invoke(
        monopoly, ["src/monopoly/examples/example_statement.pdf", "--pprint", "--single-process"]
    )

    assert result.exit_code == 0

    output = result.output
    assert "| date       | description                       |   amount |" in output
    assert "| 2023-07-02 | LAST MONTH'S BALANCE              |  -412.16 |" in output
    assert "| 2023-07-18 | CASH REBATE                       |     1.38 |" in output


def test_monopoly_no_pdf(cli_runner: CliRunner):
    with cli_runner.isolated_filesystem():
        with open("file.txt", "w") as f:
            f.write("not a pdf file")
        result = cli_runner.invoke(monopoly, ["file.txt"])
    assert result.exit_code == 1
    assert "Could not find .pdf files" in result.output


def test_get_statement_paths(test_directory: Path):
    path = test_directory
    expected = {
        path / "top_level.pdf",
        path / "top_level_2.pdf",
        path / "nested_directory/nested.pdf",
    }
    res = get_statement_paths(test_directory.iterdir())
    assert res == expected


def test_version_command(cli_runner: CliRunner):
    results = cli_runner.invoke(monopoly, args="--version")
    assert results.exit_code == 0
    assert results.stdout.startswith("monopoly, version ")
    semver_pattern = r"\d+\.\d+.\d+"
    match = re.search(semver_pattern, results.stdout)
    assert match, "Semantic version number not in output"


def test_pprint_transactions(capsys, statement):
    file = Path("test_file.md")
    transactions = [
        Transaction(transaction_date="2023-01-01", description="Transaction 1", amount=100.00),
        Transaction(transaction_date="2023-01-01", description="Transaction 2", amount=123.12),
    ]
    pprint_transactions(transactions, statement, file)
    captured = capsys.readouterr()
    expected_output = (
        "test_file.md\n"
        "+------------+---------------+----------+\n"
        "| date       | description   |   amount |\n"
        "|------------+---------------+----------|\n"
        "| 2023-01-01 | Transaction 1 |     -100 |\n"
        "| 2023-01-01 | Transaction 2 |  -123.12 |\n"
        "+------------+---------------+----------+\n"
        "\n"
    )
    assert captured.out == expected_output


def test_monopoly_extras_not_written_by_default(cli_runner: CliRunner, tmp_path: Path):
    result = cli_runner.invoke(monopoly, ["src/monopoly/examples/example_statement.pdf", "--output", str(tmp_path)])

    assert result.exit_code == 0
    assert not list(tmp_path.glob("*.extras.json"))


def test_monopoly_extras_output(cli_runner: CliRunner, tmp_path: Path, monkeypatch):
    from datetime import date
    from decimal import Decimal

    from monopoly.statements import BaseStatement

    extras = {"points_end": 12612, "credit_limit": Decimal("5000.00"), "due": date(2023, 7, 24), "card": "Gold"}
    monkeypatch.setattr(BaseStatement, "extras", property(lambda self: extras))

    result = cli_runner.invoke(
        monopoly, ["src/monopoly/examples/example_statement.pdf", "--output", str(tmp_path), "--extras"]
    )

    assert result.exit_code == 0
    assert "1 statement(s) processed" in result.output

    csv_files = list(tmp_path.glob("*.csv"))
    assert len(csv_files) == 1
    extras_file = csv_files[0].with_name(f"{csv_files[0].stem}.extras.json")
    assert extras_file.exists()

    data = json.loads(extras_file.read_text())
    assert data == {
        "bank": data["bank"],
        "statement_date": "2023-07-01",
        "extras": {"points_end": 12612, "credit_limit": "5000.00", "due": "2023-07-24", "card": "Gold"},
    }
    assert data["bank"]

    # the transactions CSV keeps its fixed 4-column contract
    assert csv_files[0].read_text().splitlines()[0] == "date,description,amount,balance"


def test_monopoly_extras_empty(cli_runner: CliRunner, tmp_path: Path):
    # a statement whose config declares no extra fields still gets a (empty) sidecar
    result = cli_runner.invoke(
        monopoly, ["src/monopoly/examples/example_statement.pdf", "--output", str(tmp_path), "--extras"]
    )

    assert result.exit_code == 0
    [extras_file] = tmp_path.glob("*.extras.json")
    assert json.loads(extras_file.read_text())["extras"] == {}


def test_pprint_transactions_shows_extras(capsys, statement, monkeypatch):
    monkeypatch.setattr(type(statement), "extras", property(lambda self: {"points_end": 12612}))
    transactions = [Transaction(transaction_date="2023-01-01", description="Transaction 1", amount=100.00)]

    pprint_transactions(transactions, statement, Path("test_file.md"))

    output = capsys.readouterr().out
    assert "| points_end |   12612 |" in output
