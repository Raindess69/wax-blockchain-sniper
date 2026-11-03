"""Offline tests: no network, no keys. Network objects are stubbed."""
from __future__ import annotations

from decimal import Decimal

import pytest

import wax_manager as wm
import wax_sniper as ws
from wax_manager import WaxManager, chunked, format_wax
from wax_sniper import MODES, ClaimSpec, WaxClaimer, WaxError


# ── helpers ────────────────────────────────────────────────────────────────
def test_format_wax_exact_8dp_and_truncates():
    assert format_wax("1.5") == "1.50000000 WAX"
    assert format_wax(Decimal("0.123456789")) == "0.12345678 WAX"  # truncate, never round up
    with pytest.raises(WaxError):
        format_wax("0")
    with pytest.raises(WaxError):
        format_wax("0.000000001")  # below 1e-8 -> zero after truncation


def test_chunked():
    assert chunked(list(range(5)), 2) == [[0, 1], [2, 3], [4]]
    assert chunked([], 3) == []


# ── claim action data matches each contract's real ABI ────────────────────
def _fields(data):
    return [d.name for d in data]


def test_atomic_claim_fields_match_abi():
    c = WaxClaimer("k", "alice1111111")
    names = _fields(c._claim_data("atomicdropsx", "claimdrop", ClaimSpec(drop_id=7), None))
    assert names == ["claimer", "drop_id", "claim_amount", "intended_delphi_median",
                     "referrer", "country"]


def test_nefty_claim_fields_match_abi():
    c = WaxClaimer("k", "alice1111111")
    names = _fields(c._claim_data("neftyblocksd", "claimdrop", ClaimSpec(drop_id=7), None))
    assert names == ["claimer", "drop_id", "amount", "intended_delphi_median", "referrer",
                     "country", "currency", "referrer_account"]


def test_nefty_proof_fields_and_requires_assets():
    c = WaxClaimer("k", "alice1111111")
    names = _fields(c._claim_data("neftyblocksd", "claimwproof", ClaimSpec(drop_id=7), [1, 2]))
    assert names == ["claimer", "drop_id", "amount", "intended_delphi_median", "referrer",
                     "asset_ids", "country", "currency", "referrer_account"]
    with pytest.raises(WaxError):
        c.claim_once(5, ClaimSpec(drop_id=7), asset_ids=None)


def test_invalid_mode_and_missing_credentials():
    with pytest.raises(WaxError):
        WaxClaimer("k", "alice1111111").claim_once(99, ClaimSpec(drop_id=1))
    with pytest.raises(WaxError):
        WaxClaimer("", "alice1111111")
    with pytest.raises(WaxError):
        WaxClaimer("k", "")
    assert set(MODES) == {1, 2, 3, 4, 5}


# ── snipe retry semantics (network stubbed) ────────────────────────────────
def test_snipe_retries_transient_errors_then_succeeds(monkeypatch):
    c = WaxClaimer("k", "alice1111111")
    calls = {"n": 0}

    def fake_claim(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("429 Too Many Requests")
        return True

    monkeypatch.setattr(c, "claim_once", fake_claim)
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)
    assert c.snipe(1, ClaimSpec(drop_id=1), cooldown=0) is True
    assert calls["n"] == 3


def test_snipe_stops_on_config_error_and_respects_max_attempts(monkeypatch):
    c = WaxClaimer("k", "alice1111111")
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)

    monkeypatch.setattr(c, "claim_once", lambda *a, **k: (_ for _ in ()).throw(WaxError("bad")))
    with pytest.raises(WaxError):
        c.snipe(1, ClaimSpec(drop_id=1))

    monkeypatch.setattr(c, "claim_once", lambda *a, **k: False)
    assert c.snipe(1, ClaimSpec(drop_id=1), max_attempts=4) is False


# ── wallet manager (network stubbed) ───────────────────────────────────────
class _FakeResp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _FakeSession:
    """Serves `total` assets in pages of wm.PAGE_SIZE, like the real API."""

    def __init__(self, total):
        self.total, self.pages = total, []

    def get(self, url, params=None, timeout=None):
        page, size = params["page"], params["limit"]
        self.pages.append(page)
        start = (page - 1) * size
        ids = [{"asset_id": str(i)} for i in range(start, min(start + size, self.total))]
        return _FakeResp({"success": True, "data": ids})


def test_get_nfts_paginates_past_first_page():
    sess = _FakeSession(total=wm.PAGE_SIZE * 2 + 5)
    ids = WaxManager(None, "alice1111111", session=sess).get_nfts()
    assert len(ids) == wm.PAGE_SIZE * 2 + 5           # old code stopped at 100
    assert sess.pages == [1, 2, 3]


def test_get_wax_balance_reads_accounts_table():
    mgr = WaxManager(None, "alice1111111")
    mgr.net = type("N", (), {"get_table_rows": lambda self, **k: [{"balance": "12.34560000 WAX"}]})()
    assert mgr.get_wax_balance() == Decimal("12.34560000")
    mgr.net = type("N", (), {"get_table_rows": lambda self, **k: []})()
    assert mgr.get_wax_balance() == 0


def test_transfer_nfts_batches(monkeypatch):
    mgr = WaxManager("k", "alice1111111")
    sent = []
    monkeypatch.setattr(mgr, "_send", lambda actions, dry_run: sent.append(actions) or "tx")
    res = mgr.transfer_nfts("bob111111111", list(range(250)))
    assert len(res) == 3 and len(sent) == 3            # 100 + 100 + 50
    assert mgr.transfer_nfts("bob111111111", []) == []


def test_send_requires_key():
    with pytest.raises(WaxError):
        WaxManager(None, "alice1111111")._send([], dry_run=True)