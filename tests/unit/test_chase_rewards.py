import csv

import pytest

from monopoly.banks.chase.chase import Chase
from monopoly.banks.chase.rewards import extract_rewards
from monopoly.pdf import PdfPage, PdfParser
from monopoly.pipeline import Pipeline
from monopoly.serialize import statement_to_dict


def rewards(*lines, heading="ULTIMATE REWARDS SUMMARY"):
    # An unrelated left-hand column must not be counted as rewards.
    return [PdfPage("\n".join("Left column 123.45".ljust(90) + line for line in (heading, *lines)))]


def test_rewards_transfers_signs_wrapped_total_and_bonus():
    summary = extract_rewards(
        rewards(
            "Previous points balance          1,000",
            "+ 1 Point per $1 earned on all purchases       100",
            "+ 3x pts on dining                     50",
            "+ New Cardmember Bonus              20,000",
            "+ Anniversary Points Boost               5",
            "+ Points moved from another account      300",
            "+ Points moved to another account       -200",
            "+ Points adjusted for refund             -10",
            "- Points redeemed this statement period     500",
            "Total points available for",
            "redemption                 20,745",
            "Page 1 of 2              9999999999",
        )
    )
    assert summary.start_balance == 1000
    assert summary.end_balance == 20745
    assert summary.earned == 150
    assert summary.bonus == 20005
    assert summary.transfers_in == 300
    assert summary.transfers_out == 200
    assert summary.adjustments == -10
    assert summary.redeemed == 500
    assert summary.reconciliation_difference == 0


def test_united_wrapped_transfer_and_ytd():
    summary = extract_rewards(
        rewards(
            "+ Miles earned on all purchases              100",
            "+ 2X Miles earned on United purchases          80",
            "Total miles transferred to United",
            "180",
            "Year-to-date miles earned on",
            "credit card              2,500",
            "Log onto united.com",
            heading="UNITED MILEAGEPLUS AWARD MILES SUMMARY",
        )
    )
    assert summary.program == "united_mileageplus"
    assert summary.start_balance is None and summary.end_balance is None
    assert summary.transfers_out == summary.earned == 180
    assert summary.year_to_date_earned == 2500
    assert summary.reconciliation_difference == 0


@pytest.mark.parametrize("previous,ending,difference", [(None, -507, None), (-507, -484, 0)])
def test_southwest_negative_balance(previous, ending, difference):
    rows = [] if previous is None else [f"Previous month's balance           {previous}"]
    rows += [
        f"+ Points earned on all other purchases     {ending if previous is None else 23}",
        "- Total Rapid Rewards transf. to",
        "Southwest               0",
        f"Rewards points balance          {ending}",
    ]
    summary = extract_rewards(rewards(*rows, heading="SOUTHWEST RAPID REWARDS CREDIT CARD SUMMARY"))
    assert summary.start_balance == previous
    assert summary.end_balance == ending
    assert summary.reconciliation_difference == difference


def test_amazon_and_unsigned_earnings():
    summary = extract_rewards(
        rewards(
            "Previous points balance         10",
            "1x on all purchases              5",
            "3.5%(3.5 Pts)/$1 addl on Chase Travel      7",
            "Total points available for",
            "redemption                 22",
            heading="YOUR PRIME VISA POINTS",
        )
    )
    assert summary.program == "amazon_rewards"
    assert summary.earned == 12 and summary.reconciliation_difference == 0


def extract(page):
    pipeline = Pipeline(PdfParser.from_pages(Chase, [page]))
    return pipeline, pipeline.extract()


def test_credit_csv_sidecar_and_json(tmp_path):
    page = (
        "\n".join(
            p.raw_text
            for p in rewards(
                "Previous points balance       100",
                "+ 1 Point per $1 earned on all purchases        20",
                "Total points available for",
                "redemption       120",
            )
        )
        + """\nACCOUNT SUMMARY
Account Number: XXXX XXXX XXXX 1234
Previous Balance       $0.00
New   Balance          $20.00
Opening/Closing Date   01/01/26 - 01/31/26
01/02  COFFEE STORE                  20.00
"""
    )
    pipeline, statement = extract(page)
    txs = pipeline.transform(statement)
    path = pipeline.load(txs, statement, tmp_path, preserve_filename=False)
    sidecar = path.with_name(path.stem + "-points.csv")
    with sidecar.open() as stream:
        row = next(csv.DictReader(stream))
    assert row["account"] == "1234" and row["earned"] == "20"
    assert row["date"] == "2026-01-31"
    assert statement_to_dict(statement, txs)["points_summary"]["reconciliation_difference"] == 0
