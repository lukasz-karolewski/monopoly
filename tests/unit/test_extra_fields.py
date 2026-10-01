import logging
import re
from datetime import date
from decimal import Decimal

import pytest
from test_utils.statements import StubStatement

from monopoly.config import DateOrder, ExtraField, StatementConfig
from monopoly.constants import EntryType
from monopoly.pdf import PdfPage


def make_statement(extra_fields=None, pages=("",), statement_date_order="DMY") -> StubStatement:
    kwargs = {} if extra_fields is None else {"extra_fields": extra_fields}
    config = StatementConfig(
        statement_type=EntryType.CREDIT,
        header_pattern="foo",
        transaction_pattern="foo",
        statement_date_pattern="foo",
        statement_date_order=DateOrder(statement_date_order),
        **kwargs,
    )
    return StubStatement(
        pages=[PdfPage(text) for text in pages],
        bank_name="example",
        config=config,
        header="foo",
    )


def test_extra_fields_default_empty():
    statement = make_statement(pages=("Previous points balance 1,234",))
    assert statement.config.extra_fields == []
    assert statement.extras == {}


def test_extra_field_requires_value_group():
    with pytest.raises(ValueError, match="value"):
        ExtraField("points", re.compile(r"points (\d+)"), "int")


def test_extra_field_rejects_unknown_type():
    with pytest.raises(ValueError, match="unsupported type"):
        ExtraField("points", re.compile(r"points (?P<value>\d+)"), "float")  # type: ignore[arg-type]


def test_extra_field_compiles_string_pattern():
    extra_field = ExtraField("points", r"points (?P<value>\d+)", "int")  # type: ignore[arg-type]
    assert isinstance(extra_field.pattern, re.Pattern)


@pytest.mark.parametrize(
    "value, type_, expected",
    [
        ("  Platinum Card  ", "str", "Platinum Card"),
        ("12,345", "int", 12345),
        (" 1 234 ", "int", 1234),
        ("$5,000.00", "decimal", Decimal("5000.00")),
        ("S$ 1,234.56", "decimal", Decimal("1234.56")),
        ("USD 99.10", "decimal", Decimal("99.10")),
        ("-12.50", "decimal", Decimal("-12.50")),
        ("24-07-2023", "date", date(2023, 7, 24)),
        ("March 12, 2022", "date", date(2022, 3, 12)),
    ],
)
def test_coerce(value, type_, expected):
    coerced = make_statement()._coerce(value, type_)
    assert coerced == expected
    assert type(coerced) is type(expected)


def test_coerce_date_respects_statement_date_order():
    assert make_statement(statement_date_order="MDY")._coerce("02/03/24", "date") == date(2024, 2, 3)
    assert make_statement(statement_date_order="DMY")._coerce("02/03/24", "date") == date(2024, 3, 2)


@pytest.mark.parametrize(
    "value, type_",
    [("12a", "int"), ("", "int"), ("N/A", "decimal"), ("1.2.3", "decimal"), ("not a date", "date")],
)
def test_coerce_failure_raises_value_error(value, type_):
    with pytest.raises((ValueError, ArithmeticError)):
        make_statement()._coerce(value, type_)


def test_extras_first_match_across_pages():
    statement = make_statement(
        extra_fields=[
            ExtraField("points", re.compile(r"(?i)points balance\s+(?P<value>[\d,]+)"), "int"),
            ExtraField("limit", re.compile(r"Credit Limit\s+(?P<value>\S+)"), "decimal"),
            ExtraField("card", re.compile(r"Card:\s*(?P<value>.+)"), "str"),
        ],
        pages=(
            "Card: Sapphire Preferred\nnothing else here",
            "POINTS BALANCE\n   12,345\nCredit Limit $5,000.00",
            "Points balance 999",
        ),
    )
    assert statement.extras == {"points": 12345, "limit": Decimal("5000.00"), "card": "Sapphire Preferred"}


def test_extras_missing_match_is_omitted():
    statement = make_statement(
        extra_fields=[
            ExtraField("points", re.compile(r"points balance\s+(?P<value>[\d,]+)"), "int"),
            ExtraField("limit", re.compile(r"Credit Limit\s+(?P<value>\S+)"), "decimal"),
        ],
        pages=("Credit Limit 1,000.00",),
    )
    assert statement.extras == {"limit": Decimal("1000.00")}


def test_extras_coercion_failure_is_skipped_with_warning(caplog):
    statement = make_statement(
        extra_fields=[
            ExtraField("points", re.compile(r"points\s+(?P<value>\S+)"), "int"),
            ExtraField("due", re.compile(r"due\s+(?P<value>\S+)"), "date"),
        ],
        pages=("points N/A\ndue 05/06/2024",),
    )
    with caplog.at_level(logging.WARNING):
        assert statement.extras == {"due": date(2024, 6, 5)}
    assert "points" in caplog.text
