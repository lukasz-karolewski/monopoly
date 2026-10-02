import re
from collections import defaultdict
from collections.abc import Iterator
from decimal import Decimal

from monopoly.constants import Direction
from monopoly.statements import CreditStatement, DebitStatement, Transaction
from monopoly.statements.base import SafetyCheckError, extract_last4

DESCRIPTION_MIN_COLUMN = 20
ACTIVITY_SECTIONS = {
    "transaction detail",
    "deposits and additions",
    "electronic withdrawal",
    "atm debit withdrawal",
    "other withdrawals",
    "fees section",
}

MONEY = r"-?\$?[\d,]+\.\d{2}"


def decimal(value: str) -> Decimal:
    return Decimal(value.replace("$", "").replace(",", "").replace(" ", ""))


class ChaseCreditStatement(CreditStatement):
    allow_empty_transactions = True

    def perform_safety_check(self) -> bool:
        text = "\n".join(page.raw_text for page in self.pages)
        previous = re.search(rf"^\s*Previous Balance\s+({MONEY})(?=\s|$)", text, re.MULTILINE)
        ending = re.search(rf"^\s*New\s+Balance\s+({MONEY})(?=\s|$)", text, re.MULTILINE)
        if previous and ending:
            total = sum((Decimal(str(tx.amount)) for tx in self.transactions), Decimal(0))
            if decimal(previous[1]) - total != decimal(ending[1]):
                msg = "Chase credit opening balance and activity do not reconcile to closing balance"
                raise SafetyCheckError(msg)
            return True
        return super().perform_safety_check()


class ChaseDebitStatement(DebitStatement):
    """Personal running-balance tables and business tables split by direction."""

    allow_empty_transactions = True
    columns = [*DebitStatement.columns, "account"]

    def _section_lines(self) -> Iterator[tuple[str, str | None, str]]:
        account = self.account
        section = ""
        for page in self.pages:
            for line in page.lines:
                if match := re.search(r"Account\s+Number:\s*(\d+)", line):
                    account = extract_last4(match[1])
                if match := re.search(r"\*start\*(.*)", line):
                    section = " ".join(match[1].split())
                elif "*end*" in line:
                    section = ""
                yield section, account, line

    @staticmethod
    def _continuation(line: str) -> bool:
        stripped = line.strip()
        return (
            bool(stripped)
            and line.index(stripped) >= DESCRIPTION_MIN_COLUMN
            and not stripped.startswith(("Total ", "Ending", "Beginning", "DATE", "Page ", "*"))
            and not re.search(r"\s{10,}", stripped)
        )

    def get_transactions(self) -> list[Transaction]:
        transactions = []
        last = None
        for section, account, line in self._section_lines():
            if section not in ACTIVITY_SECTIONS or "*start*" in line:
                last = None
                continue
            if match := self.pattern.match(line):
                values = match.groupdict()
                amount = decimal(values["amount"])
                if section not in {"transaction detail", "deposits and additions"}:
                    amount = -abs(amount)
                last = Transaction(
                    transaction_date=values["transaction_date"],
                    description=values["description"],
                    amount=float(amount),
                    balance=float(decimal(values["balance"])) if values.get("balance") else None,
                    direction=Direction.CREDIT if amount >= 0 else Direction.DEBIT,
                    currency=self.config.currency,
                    account=account,
                )
                transactions.append(last)
            elif line.strip() and last is not None:
                if self._continuation(line):
                    last.description = " ".join((last.description + " " + line.strip()).split())
                else:
                    last = None
        return transactions

    def perform_safety_check(self) -> bool:
        balances: dict[str | None, dict[str, Decimal]] = defaultdict(dict)
        for section, account, line in self._section_lines():
            if section == "summary" and (
                match := re.search(rf"(Beginning|Ending)\s+Balance\s+(?:\d+\s+)?({MONEY})\s*$", line)
            ):
                balances[account][match[1]] = decimal(match[2])
        totals: dict[str | None, Decimal] = defaultdict(lambda: Decimal(0))
        for tx in self.transactions:
            totals[tx.account] += Decimal(str(tx.amount))
        if not balances:
            msg = "Chase checking balances not found"
            raise SafetyCheckError(msg)
        for account, values in balances.items():
            if set(values) != {"Beginning", "Ending"} or values["Beginning"] + totals[account] != values["Ending"]:
                msg = f"Chase checking activity does not reconcile for account {account}"
                raise SafetyCheckError(msg)
        return True
