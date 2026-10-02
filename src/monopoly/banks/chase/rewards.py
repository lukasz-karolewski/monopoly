import re
from collections.abc import Iterator

from monopoly.pdf import PdfPage
from monopoly.statements.points import PointsSummary

ANCHOR = re.compile(r"Previous points balance|Previous month's balance|\+\s*.*?(?:mile|pts|points)", re.IGNORECASE)
FIELD_PATTERNS = (
    ("start_balance", r"^previous", False),
    ("end_balance", r"redemption|^rewards points balance$", False),
    ("year_to_date_earned", r"year-to-date", False),
    ("transfers_in", r"moved from", True),
    ("transfers_out", r"moved to|transferred|transf\.", True),
    ("redeemed", r"redeemed", True),
    ("adjustments", r"adjusted", True),
    ("bonus", r"new cardmember|anniversary", True),
)


def _program(text: str) -> str | None:
    if "MILEAGEPLUS" in text:
        return "united_mileageplus"
    if "RAPID" in text and "REWARDS" in text:
        return "southwest_rapid_rewards"
    if "Previous points balance" in text:
        return "amazon_rewards" if re.search(r"amazon|prime visa", text, re.IGNORECASE) else "ultimate_rewards"
    return None


def _reward_rows(lines: list[str]) -> Iterator[tuple[str, int]]:
    anchor = next(((idx, match.start()) for idx, line in enumerate(lines) if (match := ANCHOR.search(line))), None)
    if anchor is None:
        return
    start, column = anchor
    pending = ""
    for line in lines[start:]:
        value = line[column:].strip()
        if re.match(r"Start redeeming|Learn more|View your|Log onto|Thank you|Reward your", value):
            return
        if not value:
            continue
        match = re.fullmatch(r"(.*?)\s{2,}(-?[\d,]+)", value)
        if match:
            label, number = match.groups()
        elif re.fullmatch(r"-?[\d,]+", value):
            label, number = "", value
        else:
            pending = f"{pending} {value}".strip()
            continue
        if pending and (not label or label in {"redemption", "Southwest", "credit card"}):
            label = f"{pending} {label}".strip()
        pending = ""
        yield label, int(number.replace(",", ""))


def _apply_row(summary: PointsSummary, label: str, amount: int) -> str:
    for field, pattern, additive in FIELD_PATTERNS:
        if re.search(pattern, label, re.IGNORECASE):
            if field in {"transfers_out", "redeemed"}:
                amount = abs(amount)
            setattr(summary, field, getattr(summary, field) + amount if additive else amount)
            return field
    if label.startswith(("+", "-")) or re.match(r"\d.*(?:on |back)", label):
        summary.earned += amount
    return "earned"


def extract_rewards(pages: list[PdfPage]) -> PointsSummary | None:
    """Read the first-page rewards column, stopping before marketing copy."""
    if not pages or (program := _program(pages[0].raw_text)) is None:
        return None
    summary = PointsSummary(program)
    has_closing_balance = "Rewards points balance" in pages[0].raw_text
    for label, amount in _reward_rows(pages[0].lines):
        field = _apply_row(summary, label, amount)
        if field in {"end_balance", "year_to_date_earned"}:
            break
        if program == "southwest_rapid_rewards" and field == "transfers_out" and not has_closing_balance:
            break
    summary.reconcile()
    return summary
