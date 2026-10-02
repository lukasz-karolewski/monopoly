from dataclasses import dataclass


@dataclass
class PointsSummary:
    """Statement-level rewards in whole points/miles; missing balances stay unknown."""

    program: str
    start_balance: int | None = None
    end_balance: int | None = None
    earned: int = 0
    bonus: int = 0
    adjustments: int = 0
    transfers_in: int = 0
    transfers_out: int = 0
    redeemed: int = 0
    year_to_date_earned: int | None = None
    reconciliation_difference: int | None = None

    def reconcile(self) -> None:
        if self.start_balance is not None and self.end_balance is not None:
            expected = (
                self.start_balance
                + self.earned
                + self.bonus
                + self.adjustments
                + self.transfers_in
                - self.transfers_out
                - self.redeemed
            )
            self.reconciliation_difference = self.end_balance - expected
        elif self.end_balance is None and self.program in {"united_mileageplus", "southwest_rapid_rewards"}:
            # Older airline summaries report only this cycle's earnings and transfer.
            self.reconciliation_difference = self.earned + self.bonus + self.adjustments - self.transfers_out
