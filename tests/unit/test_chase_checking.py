import csv
from io import BytesIO

import pymupdf
import pytest

from monopoly.banks.chase.chase import Chase
from monopoly.pdf import PdfDocument, PdfParser
from monopoly.pipeline import Pipeline
from monopoly.statements.base import SafetyCheckError


def checking_page(activity, begin="100.00", end="120.00", account="000000000001234"):
    return f"""January 01, 2026 through January 31, 2026
Account Number: {account}
*start*summary
CHECKING SUMMARY
Beginning Balance       ${begin}
Ending Balance          ${end}
*end*summary
{activity}
"""


def extract(page):
    pipeline = Pipeline(PdfParser.from_pages(Chase, [page]))
    return pipeline, pipeline.extract()


def test_business_checking_directions_and_multiline(tmp_path):
    page = checking_page("""*start*deposits and additions
DATE  DESCRIPTION                         AMOUNT
01/02  Online Transfer                      50.00
*end*deposits and additions
*start*electronic withdrawal
DATE  DESCRIPTION                         AMOUNT
01/03  Utility Payment                      25.00
       Continuation should be excluded at this margin
*end*electronic withdrawal
*start*fees section
01/31  Monthly Service Fee                   5.00
*end*fees section
*start*daily ending balance3
01/31                                       120.00
*end*daily ending balance3""")
    pipeline, statement = extract(page)
    txs = pipeline.transform(statement)
    assert [tx.amount for tx in txs] == [50, -25, -5]
    assert all(tx.account == "1234" for tx in txs)
    assert txs[0].date == "2026-01-02"
    output = pipeline.load(txs, statement, tmp_path, preserve_filename=False)
    with output.open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["account"] == "1234"
    assert not list(tmp_path.glob("*-points.csv"))


def test_consolidated_checking_accounts_and_checks_not_duplicated():
    page = checking_page(
        """*start*checks paid section2
9999 ^   01/02      $20.00
*end*checks paid section2
*start*transaction detail
01/02  Check # 9999           -20.00      80.00
*end*transaction detail""",
        end="80.00",
    )
    page += checking_page(
        """*start*transaction detail
01/03  Transfer               30.00      230.00
*end*transaction detail""",
        begin="200.00",
        end="230.00",
        account="000000000005678",
    )
    _, statement = extract(page)
    assert [(tx.amount, tx.account) for tx in statement.transactions] == [(-20, "1234"), (30, "5678")]


def test_checking_rejects_missing_transaction():
    with pytest.raises(SafetyCheckError, match="does not reconcile"):
        extract(checking_page("*start*transaction detail\n*end*transaction detail"))


def test_zero_activity_statement_exports_header(tmp_path):
    pipeline, statement = extract(checking_page("", end="100.00"))
    output = pipeline.load([], statement, tmp_path, preserve_filename=False)
    assert output.read_text().strip() == "date,description,amount,balance,account"


def test_checking_recovers_amount_with_shifted_baseline_and_excludes_vertical_text():
    document = pymupdf.open()
    page = document.new_page()
    for y, line in enumerate(
        [
            "JPMorgan Chase Bank, N.A.",
            "January 01, 2026 through January 31, 2026",
            "Account Number: 000000000001234",
            "*start*summary",
            "CHECKING SUMMARY",
            "Beginning Balance       $100.00",
            "Ending Balance       $120.00",
            "*end*summary",
            "*start*transaction detail",
            "DATE    DESCRIPTION    AMOUNT    BALANCE",
        ]
    ):
        page.insert_text((30, 30 + y * 20), line, fontsize=10)
    page.insert_text((30, 240), "01/02", fontsize=10)
    page.insert_text((90, 240), "Transfer", fontsize=10)
    page.insert_text((400, 239.5), "20.00", fontsize=10)
    page.insert_text((500, 240), "120.00", fontsize=10)
    page.insert_text((580, 240), "9999999999", fontsize=10, rotate=90)
    page.insert_text((30, 260), "*end*transaction detail", fontsize=10)
    with PdfDocument(file_bytes=BytesIO(document.tobytes())) as source:
        statement = Pipeline(PdfParser(Chase, source)).extract()
    assert [tx.amount for tx in statement.transactions] == [20]


def credit_page(previous, closing, activity=""):
    return f"""ACCOUNT SUMMARY
Account Number: XXXX XXXX XXXX 1234
Previous Balance       ${previous}
New   Balance          ${closing}
Opening/Closing Date   01/01/26 - 01/31/26
{activity}
"""


def test_zero_activity_credit_statement():
    _, statement = extract(credit_page("0.00", "0.00"))
    assert statement.transactions == []
    assert statement.account == "1234"
    assert statement.statement_date.isoformat() == "2026-01-31T00:00:00"


def test_credit_reconciles_activity_against_opening_balance():
    _, statement = extract(credit_page("100.00", "120.00", "01/02  COFFEE STORE        20.00"))
    assert [tx.amount for tx in statement.transactions] == [-20]
    with pytest.raises(SafetyCheckError, match="do not reconcile"):
        extract(credit_page("100.00", "125.00", "01/02  COFFEE STORE        20.00"))
