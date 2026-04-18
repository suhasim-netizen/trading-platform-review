"""Whitelist helpers for order stream fill filtering."""

from execution.order_tracker import _is_our_symbol


def test_equity_symbols_allowed() -> None:
    assert _is_our_symbol("TSM")
    assert _is_our_symbol("$TSM")
    assert _is_our_symbol("@LLY")


def test_index_option_like_spxw_rejected() -> None:
    assert not _is_our_symbol("$SPXW.X")
    assert not _is_our_symbol("SPXW.X")


def test_futures_roots_and_contracts() -> None:
    assert _is_our_symbol("MES")
    assert _is_our_symbol("MESM26")
    assert _is_our_symbol("@MNQ")
    assert _is_our_symbol("MNQM26")
