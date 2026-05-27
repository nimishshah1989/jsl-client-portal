"""Tests for ingestion_service._derive_cash_flows_from_nav.

Regression suite for the production incident 2026-05-26 where the function
treated every incremental daily NAV upload as if it started from corpus=0,
synthesising a phantom INFLOW for the full corpus on every upload. The fix
introduces a ``prior_corpus`` parameter (the most recent invested_amount in
cpp_nav_series strictly before the upload's earliest date) so daily uploads
correctly produce zero phantom cash flows.
"""

from datetime import date
from decimal import Decimal

from backend.services.ingestion_service import _derive_cash_flows_from_nav


class TestDeriveCashFlowsFromNav:
    """Regression tests for cash-flow derivation from corpus changes."""

    def test_derive_cash_flows_first_backfill(self):
        """First backfill (prior_corpus=0): every corpus step-up becomes an INFLOW row."""
        records = [
            {"date": date(2021, 7, 15), "corpus": Decimal("3000000")},
            {"date": date(2021, 7, 16), "corpus": Decimal("3000000")},  # no change
            {"date": date(2023, 2, 10), "corpus": Decimal("4500000")},  # +15L
            {"date": date(2023, 2, 20), "corpus": Decimal("6000000")},  # +15L
            {"date": date(2023, 6, 1),  "corpus": Decimal("7000000")},  # +10L
        ]
        flows = _derive_cash_flows_from_nav("BJ53", records, prior_corpus=Decimal("0"))

        assert len(flows) == 4
        assert all(f["flow_type"] == "INFLOW" for f in flows)
        assert flows[0]["date"] == date(2021, 7, 15)
        assert flows[0]["amount"] == Decimal("3000000")
        assert flows[1]["date"] == date(2023, 2, 10)
        assert flows[1]["amount"] == Decimal("1500000")
        assert flows[2]["date"] == date(2023, 2, 20)
        assert flows[2]["amount"] == Decimal("1500000")
        assert flows[3]["date"] == date(2023, 6, 1)
        assert flows[3]["amount"] == Decimal("1000000")
        assert all(f["client_code"] == "BJ53" for f in flows)

    def test_derive_cash_flows_incremental_no_change(self):
        """Daily incremental upload, corpus unchanged → zero cash-flow rows derived.

        This is the production-incident regression test: previously, prior_corpus
        defaulted to 0 and a single-row upload with corpus=19,90,506 produced a
        phantom INFLOW of ₹19,90,506. With prior_corpus=19,90,506 (looked up from
        cpp_nav_series.invested_amount for the prior day), no flow is produced.
        """
        records = [
            {"date": date(2026, 5, 15), "corpus": Decimal("1990506")},
        ]
        flows = _derive_cash_flows_from_nav(
            "BJ53", records, prior_corpus=Decimal("1990506")
        )
        assert flows == []

    def test_derive_cash_flows_incremental_real_infusion(self):
        """Daily incremental upload with a true new infusion → exactly one INFLOW
        for the delta (NOT the absolute corpus)."""
        records = [
            {"date": date(2026, 5, 16), "corpus": Decimal("2990506")},
        ]
        flows = _derive_cash_flows_from_nav(
            "BJ53", records, prior_corpus=Decimal("1990506")
        )
        assert len(flows) == 1
        assert flows[0]["flow_type"] == "INFLOW"
        assert flows[0]["amount"] == Decimal("1000000")
        assert flows[0]["date"] == date(2026, 5, 16)
        assert flows[0]["client_code"] == "BJ53"

    def test_derive_cash_flows_outflow(self):
        """Daily incremental upload with corpus DECREASE → one OUTFLOW row for
        the absolute delta."""
        records = [
            {"date": date(2026, 5, 17), "corpus": Decimal("1500000")},
        ]
        flows = _derive_cash_flows_from_nav(
            "BJ53", records, prior_corpus=Decimal("1990506")
        )
        assert len(flows) == 1
        assert flows[0]["flow_type"] == "OUTFLOW"
        assert flows[0]["amount"] == Decimal("490506")
        assert flows[0]["date"] == date(2026, 5, 17)

    def test_default_prior_corpus_preserves_backfill_behaviour(self):
        """Calling without the prior_corpus kwarg must behave identically to
        passing Decimal('0') — preserves backward compatibility for the
        true-first-time-backfill code path."""
        records = [
            {"date": date(2021, 7, 15), "corpus": Decimal("3000000")},
            {"date": date(2023, 2, 10), "corpus": Decimal("4500000")},
        ]
        flows_default = _derive_cash_flows_from_nav("BJ53", records)
        flows_explicit = _derive_cash_flows_from_nav(
            "BJ53", records, prior_corpus=Decimal("0")
        )
        assert flows_default == flows_explicit
