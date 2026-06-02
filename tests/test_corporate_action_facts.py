from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.quant_sim.corporate_actions import AkshareCorporateActionProvider
from app.quant_sim.corporate_action_facts import (
    CorporateActionApplicationCommand,
    CorporateActionApplicationService,
    CorporateActionCoverage,
    CorporateActionFact,
    CorporateActionFactService,
    CorporateActionFactStore,
    CorporateActionQuery,
    CorporateActionScope,
    build_action_ref,
)
from app.quant_sim.db import QuantSimDB


class FakeCorporateActionProvider:
    def __init__(self, actions=None, *, fail: bool = False):
        self.actions = list(actions or [])
        self.fail = fail
        self.calls: list[tuple[str, datetime, datetime]] = []

    def get_actions(self, stock_code: str, start_datetime: datetime, end_datetime: datetime):
        self.calls.append((stock_code, start_datetime, end_datetime))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return list(self.actions)


def test_action_ref_is_deterministic_and_normalizes_terms():
    first = build_action_ref(
        data_version="ca_v1",
        market="cn",
        stock_code="300857",
        action_type="mixed_dividend_share",
        ex_date="2026-02-09",
        record_date="2026-02-06",
        bonus_share_ratio=0.4000,
        cash_dividend_per_share=0.200,
    )
    second = build_action_ref(
        data_version="ca_v1",
        market="CN",
        stock_code="300857",
        action_type="mixed_dividend_share",
        ex_date="2026-02-09",
        record_date="2026-02-06",
        bonus_share_ratio=0.4,
        cash_dividend_per_share=0.2,
    )
    assert first == second
    assert first == "ca:ca_v1:CN:300857:mixed_dividend_share:2026-02-09:2026-02-06:0.4:0.2"


def test_akshare_provider_normalizes_action_types_and_uses_cache():
    class FakeAkApi:
        def __init__(self):
            self.calls = 0

        def stock_history_dividend_detail(self, symbol, indicator):
            self.calls += 1
            assert symbol == "300857"
            assert indicator == "分红"
            return pd.DataFrame(
                [
                    ["2026-01-01", 2.0, 2.0, 2.0, "实施", "2026-02-09", "2026-02-06", ""],
                    ["2026-01-01", 0.0, 3.0, 0.0, "实施", "2026-03-01", "2026-02-26", ""],
                    ["2026-01-01", 0.0, 0.0, 1.0, "实施", "2026-04-01", "2026-03-30", ""],
                    ["2026-01-01", 0.0, 0.0, 0.0, "实施", "2026-05-01", "2026-04-28", ""],
                    ["2026-01-01", 1.0],
                ]
            )

    api = FakeAkApi()
    provider = AkshareCorporateActionProvider(ak_api=api)

    actions = provider.get_actions("300857", datetime(2026, 1, 1), datetime(2026, 4, 30))
    cached = provider.get_actions("300857", datetime(2026, 1, 1), datetime(2026, 4, 30))

    assert [item["action_type"] for item in actions] == [
        "mixed_dividend_share",
        "share_transfer",
        "cash_dividend",
    ]
    assert actions[0]["bonus_share_ratio"] == 0.4
    assert actions[0]["cash_dividend_per_share"] == 0.2
    assert actions[0]["market"] == "CN"
    assert cached == actions
    assert api.calls == 1


def test_akshare_provider_handles_empty_invalid_and_prepare_paths():
    class EmptyAkApi:
        def stock_history_dividend_detail(self, symbol, indicator):
            del symbol, indicator
            return pd.DataFrame([["bad-date", "bad-number", None, "bad-cash", "", "bad-date", "bad-date"]])

    class BlankAkApi:
        def stock_history_dividend_detail(self, symbol, indicator):
            del symbol, indicator
            return pd.DataFrame()

    class FailingAkApi:
        def stock_history_dividend_detail(self, symbol, indicator):
            del symbol, indicator
            raise RuntimeError("provider down")

    provider = AkshareCorporateActionProvider(ak_api=EmptyAkApi())
    provider.prepare(["300857"], datetime(2026, 1, 1), datetime(2026, 1, 31))

    assert provider.get_actions("", datetime(2026, 1, 1), datetime(2026, 1, 31)) == []
    assert provider.get_actions("300857", datetime(2026, 1, 1), datetime(2026, 1, 31)) == []
    assert AkshareCorporateActionProvider(ak_api=BlankAkApi()).get_actions(
        "300857",
        datetime(2026, 1, 1),
        datetime(2026, 1, 31),
    ) == []
    assert AkshareCorporateActionProvider(ak_api=FailingAkApi()).get_actions(
        "300857",
        datetime(2026, 1, 1),
        datetime(2026, 1, 31),
    ) == []


def test_local_first_uses_coverage_and_skips_provider(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    provider = FakeCorporateActionProvider(
        [
            {
                "stock_code": "300857",
                "market": "CN",
                "action_type": "cash_dividend",
                "ex_date": "2026-02-09",
                "record_date": "2026-02-06",
                "bonus_share_ratio": 0,
                "cash_dividend_per_share": 0.2,
                "description": "fixture dividend",
            }
        ]
    )
    service = CorporateActionFactService(CorporateActionFactStore(db), provider=provider)
    query = CorporateActionQuery(
        stock_code="300857",
        market="CN",
        start_datetime=datetime(2026, 1, 1),
        end_datetime=datetime(2026, 5, 11),
    )

    first = service.get_actions(query)
    second = service.get_actions(query)

    assert len(first.facts) == 1
    assert len(second.facts) == 1
    assert first.summary["remote_fetched"] == 1
    assert second.summary["local_hit"] == 1
    assert len(provider.calls) == 1


def test_partial_coverage_fetches_only_uncovered_range(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    store = CorporateActionFactStore(db)
    store.upsert_coverage(
        CorporateActionCoverage(
            stock_code="300857",
            market="CN",
            start_date="2026-01-01",
            end_date="2026-01-31",
            provider="akshare",
            source_status="empty_range",
            reason_code="ok",
            checked_at="2026-02-01 09:00:00",
        )
    )
    provider = FakeCorporateActionProvider(
        [
            {
                "stock_code": "300857",
                "market": "CN",
                "action_type": "cash_dividend",
                "ex_date": "2026-03-03",
                "record_date": "2026-02-27",
                "bonus_share_ratio": 0,
                "cash_dividend_per_share": 0.2,
                "description": "fixture dividend",
            }
        ]
    )
    service = CorporateActionFactService(store, provider=provider)
    query = CorporateActionQuery(
        stock_code="300857",
        market="CN",
        start_datetime=datetime(2026, 1, 1),
        end_datetime=datetime(2026, 3, 31),
    )

    result = service.get_actions(query)

    assert result.summary["partial_missing"] == 0
    assert result.summary["remote_fetched"] == 1
    assert len(result.facts) == 1
    assert len(provider.calls) == 1
    _, start_dt, end_dt = provider.calls[0]
    assert start_dt.date().isoformat() == "2026-02-01"
    assert end_dt.date().isoformat() == "2026-03-31"


def test_provider_failed_retry_expires_and_allows_new_attempt(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    failing = FakeCorporateActionProvider(fail=True)
    service = CorporateActionFactService(CorporateActionFactStore(db), provider=failing, retry_minutes=30)
    query = CorporateActionQuery(
        stock_code="300857",
        market="CN",
        start_datetime=datetime(2026, 1, 1),
        end_datetime=datetime(2026, 1, 31),
    )

    first = service.get_actions(query)
    second = service.get_actions(query)
    assert first.summary["provider_failed"] == 1
    assert second.summary["provider_failed"] == 1
    assert len(failing.calls) == 1

    conn = db._connect()
    conn.execute(
        """
        UPDATE corporate_action_coverage
        SET retry_after = '2026-01-01 00:00:00', valid_until = '2026-01-01 00:00:00'
        WHERE stock_code = '300857'
        """
    )
    conn.commit()
    conn.close()

    recovering = FakeCorporateActionProvider([])
    retrying = CorporateActionFactService(CorporateActionFactStore(db), provider=recovering, retry_minutes=30)
    third = retrying.get_actions(query)

    assert third.summary["empty_range"] == 1
    assert len(recovering.calls) == 1


def test_due_application_applies_prior_ex_date_once_per_scope(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    _seed_position(db, "300857")
    store = CorporateActionFactStore(db)
    fact = store.upsert_facts(
        [
            CorporateActionFact(
                stock_code="300857",
                market="CN",
                action_type="cash_dividend",
                ex_date="2026-02-09",
                record_date="2026-02-06",
                cash_dividend_per_share=0.2,
                description="fixture dividend",
            )
        ]
    )[0]
    service = CorporateActionFactService(store, provider=FakeCorporateActionProvider([]))
    app = CorporateActionApplicationService()

    first = app.apply_due_actions(
        CorporateActionApplicationCommand(
            account_db=db,
            fact_service=service,
            scope=CorporateActionScope(scope_type="historical_replay", scope_id="101"),
            checkpoint=datetime(2026, 5, 11, 10),
        )
    )
    second = app.apply_due_actions(
        CorporateActionApplicationCommand(
            account_db=db,
            fact_service=service,
            scope=CorporateActionScope(scope_type="historical_replay", scope_id="101"),
            checkpoint=datetime(2026, 5, 11, 10),
        )
    )

    conn = db._connect()
    rows = conn.execute("SELECT * FROM sim_corporate_action_applications").fetchall()
    account = conn.execute("SELECT available_cash FROM sim_account WHERE id = 1").fetchone()
    conn.close()
    assert first.applied_refs == [fact.normalized_ref()]
    assert second.applied_count == 0
    assert len(rows) == 1
    assert rows[0]["scope_type"] == "historical_replay"
    assert rows[0]["scope_id"] == "101"
    assert float(account["available_cash"]) == 100020.0


def test_unsupported_fact_is_persisted_but_not_applied(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    _seed_position(db, "300857")
    store = CorporateActionFactStore(db)
    store.upsert_facts(
        [
            CorporateActionFact(
                stock_code="300857",
                market="CN",
                action_type="unsupported",
                ex_date="2026-02-09",
                record_date="2026-02-06",
                source_status="unsupported",
                reason_code="unsupported_action_type",
                raw={"type": "rights_issue"},
            )
        ]
    )
    service = CorporateActionFactService(store, provider=FakeCorporateActionProvider([]))
    result = CorporateActionApplicationService().apply_due_actions(
        CorporateActionApplicationCommand(
            account_db=db,
            fact_service=service,
            scope=CorporateActionScope(scope_type="live", scope_id="live"),
            checkpoint=datetime(2026, 5, 11, 10),
        )
    )

    conn = db._connect()
    count = conn.execute("SELECT COUNT(*) FROM sim_corporate_action_applications").fetchone()[0]
    conn.close()
    assert result.applied_count == 0
    assert result.skipped_count == 1
    assert count == 0


def _seed_position(db: QuantSimDB, stock_code: str) -> None:
    conn = db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sim_positions
        (stock_code, stock_name, quantity, avg_price, latest_price, market_value, status, opened_at, updated_at)
        VALUES (?, ?, 100, 10, 10, 1000, 'holding', '2026-01-01 10:00:00', '2026-01-01 10:00:00')
        """,
        (stock_code, stock_code),
    )
    position_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO sim_position_lots
        (position_id, lot_id, stock_code, quantity, remaining_quantity, entry_price, entry_time, entry_date, unlock_date, status)
        VALUES (?, ?, ?, 100, 100, 10, '2026-01-01 10:00:00', '2026-01-01', '2026-01-02', 'available')
        """,
        (position_id, f"{stock_code}-lot-1", stock_code),
    )
    conn.commit()
    conn.close()
