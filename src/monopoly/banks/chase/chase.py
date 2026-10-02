import re

from monopoly.banks.base import BankBase
from monopoly.banks.chase.layout import checking_pages
from monopoly.banks.chase.statements import ChaseCreditStatement, ChaseDebitStatement
from monopoly.config import DateOrder, MultilineConfig, StatementConfig
from monopoly.constants import EntryType, SharedPatterns
from monopoly.constants.date import ISO8601
from monopoly.identifiers import MetadataIdentifier, TextIdentifier


class Chase(BankBase):
    name = "chase"

    credit = StatementConfig(
        currency="USD",
        statement_type=EntryType.CREDIT,
        statement_date_pattern=re.compile(
            r"(?:Statement Date:\s+|Opening/Closing Date\s+\d{2}/\d{2}/\d{2}\s*-\s*)(\d{2}/\d{2}/\d{2})"
        ),
        # "Opening/Closing Date  12/18/18 - 01/17/19": opening date is the period start
        period_start_pattern=re.compile(r"Opening/Closing Date\s+(\d{2}/\d{2}/\d{2})\s*-"),
        # "Account Number: 1234 5678 9012 2037" in the account summary block
        account_pattern=re.compile(r"(?i)Account Number:\s+(?P<account>[\dX]{4} [\dX]{4} [\dX]{4} \d{4})"),
        statement_date_order=DateOrder("MDY"),
        transaction_date_order=DateOrder("MDY"),
        header_pattern=re.compile(r"(?:.*Transaction.*Merchant Name .*\$ Amount|ACCOUNT SUMMARY)"),
        transaction_date_format="%m/%d",
        transaction_pattern=re.compile(
            rf"(?P<transaction_date>{ISO8601.MM_DD})\s+"
            + SharedPatterns.DESCRIPTION
            + r"(?P<direction>\-)?"
            + r"(?P<amount>(\d{1,3}(,\d{3})*|\d*)\.\d+)$"
        ),
        multiline_config=MultilineConfig(multiline_descriptions=True),
    )

    identifiers = [
        [TextIdentifier("JPMorgan Chase Bank, N.A.")],
        [TextIdentifier("www.chase.com/cardhelp")],
        [TextIdentifier("www.chase.com/united")],
        [TextIdentifier("www.chase.com/amazon")],
        [TextIdentifier("www.chase.com/Southwest")],
        [
            MetadataIdentifier(
                format="PDF 1.7",
                producer="OpenText Output Transformation Engine - 23.4",
            ),
            TextIdentifier("Chase"),
        ],
    ]

    debit = StatementConfig(
        currency="USD",
        statement_type=EntryType.DEBIT,
        statement_date_pattern=re.compile(r"through\s+([A-Za-z]+\s+\d{2},\s+\d{4})"),
        period_start_pattern=re.compile(r"([A-Za-z]+\s+\d{2},\s+\d{4})\s+through"),
        account_pattern=re.compile(r"(?:Primary\s+Account|Account\s+Number):\s*(?P<account>\d+)"),
        statement_date_order=DateOrder("MDY"),
        transaction_date_order=DateOrder("MDY"),
        transaction_date_format="%m/%d",
        header_pattern=re.compile(r"CHECKING\s+SUMMARY"),
        transaction_pattern=re.compile(
            r"^\s*(?P<transaction_date>\d{2}/\d{2})\s+"
            r"(?P<description>.*?)\s{2,}(?P<amount>-?\s*\$?[\d,]+\.\d{2})"
            r"(?:\s+(?P<balance>-?\s*\$?[\d,]+\.\d{2}))?\s*$"
        ),
    )

    statement_classes = {EntryType.CREDIT: ChaseCreditStatement, EntryType.DEBIT: ChaseDebitStatement}
    statement_configs = [debit, credit]

    @classmethod
    def statement_candidates(cls, parser):
        if parser.document is not None and cls.debit.find_header(parser.pages):
            parser.pages = checking_pages(parser.document)
        yield from super().statement_candidates(parser)
