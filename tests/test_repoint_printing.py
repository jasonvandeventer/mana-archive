"""Printing repoint (issue #78).

Pins the acceptance criteria: repointing changes a row's card_id in place (with
full audit), preserves the row id + every FK reference, upserts an unknown target
printing from Scryfall, and rejects a target that is a DIFFERENT card (oracle_id
mismatch) or a Scryfall lookup failure. Scryfall is mocked — no network.
"""

from __future__ import annotations

import re

import pytest

from app import inventory_service
from app.inventory_service import InventoryRowNotFound, repoint_inventory_row_printing
from app.models import (
    Card,
    Deck,
    DeckCardShare,
    InventoryRow,
    ShowcaseItem,
    StorageLocation,
    TradeItem,
    TransactionLog,
)


def test_deck_modal_corrects_unowned_printing(client, db, user, monkeypatch, tmp_path):
    """Follow the rendered form: one physical card, no spare copy to swap in."""
    from app.routes import decks

    old = _card(db, "src-1", "Blackblade Reforged", "dmc", "178")
    old.set_name = "Dominaria United Commander"
    loc = StorageLocation(user_id=user.id, name="Percussive Maintenance", type="deck")
    db.add(loc)
    db.flush()
    deck = Deck(user_id=user.id, name=loc.name, storage_location_id=loc.id)
    db.add(deck)
    db.flush()
    row = _row(db, user.id, old, storage_location_id=loc.id, role="commander", notes="Keep me")
    target = {
        "scryfall_id": "tgt-2",
        "name": old.name,
        "set_code": "dom",
        "set_name": "Dominaria",
        "collector_number": "211",
    }
    printings = [
        dict(
            target,
            finishes=["nonfoil", "foil"],
            released_at="2018-04-27",
            frame_effects=[],
            image_uri_normal=None,
            image_uri_small=None,
        ),
        dict(
            target,
            scryfall_id=old.scryfall_id,
            set_code="dmc",
            collector_number="178",
            set_name=old.set_name,
        ),
    ]
    printings[1].update(
        finishes=["nonfoil"],
        released_at="2022-09-09",
        frame_effects=[],
        image_uri_normal=None,
        image_uri_small=None,
    )
    monkeypatch.setattr(decks, "fetch_card_printings", lambda name: printings)
    _mock_scryfall(monkeypatch, {"src-1": "ORA", "tgt-2": "ORA"}, {"tgt-2": target})
    page = client.get(f"/decks/{deck.id}/rows/{row.id}/printings-modal")
    assert page.status_code == 200
    (tmp_path / "modal.html").write_text(page.text)
    forms = re.findall(r"<form\b([^>]*)>(.*?)</form>", page.text, re.S)
    corrections = [(attrs, body) for attrs, body in forms if "repoint-printing" in attrs]
    assert len(corrections) == 2, "The modal must offer correction without owning a spare"
    attrs, body = next((a, b) for a, b in corrections if 'value="tgt-2"' in b)
    assert "disabled" not in body
    assert "hx-post" not in attrs  # full redirect refreshes the card AND hero totals
    current = next(b for a, b in corrections if 'value="src-1"' in b)
    assert "disabled" in current
    action = re.search(r'action="([^"]+)"', attrs).group(1)
    data = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', body))
    referer = f"http://testserver/decks/{deck.id}?sort=price&direction=desc"
    response = client.post(action, data=data, headers={"referer": referer}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == referer
    db.refresh(row)
    assert db.get(Card, row.card_id).scryfall_id == "tgt-2"
    assert (row.quantity, row.storage_location_id, row.finish, row.role, row.notes) == (
        1,
        loc.id,
        "normal",
        "commander",
        "Keep me",
    )
    assert db.query(InventoryRow).filter_by(user_id=user.id).count() == 1
    log = db.query(TransactionLog).filter_by(inventory_row_id=row.id).one()
    assert (log.event_type, log.quantity_delta) == ("repoint_printing", 0)


def _card(db, scryfall_id, name, set_code, coll):
    c = Card(scryfall_id=scryfall_id, name=name, set_code=set_code, collector_number=coll)
    db.add(c)
    db.flush()
    return c


def _row(db, user_id, card, **kw):
    r = InventoryRow(
        card_id=card.id,
        user_id=user_id,
        quantity=kw.pop("quantity", 1),
        finish=kw.pop("finish", "normal"),
        is_pending=kw.pop("is_pending", False),
        **kw,
    )
    db.add(r)
    db.commit()
    return r


def _mock_scryfall(monkeypatch, oracle_by_id, payload_by_id):
    """oracle_by_id: {scryfall_id: oracle_id or None}; payload_by_id used for the
    target upsert. None oracle / missing payload models a Scryfall failure."""
    monkeypatch.setattr(inventory_service, "fetch_oracle_id", lambda sid: oracle_by_id.get(sid))
    monkeypatch.setattr(
        inventory_service, "fetch_card_by_scryfall_id", lambda sid: payload_by_id.get(sid)
    )


def test_happy_path_repoints_and_audits(db, user, monkeypatch):
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, user.id, old)
    _mock_scryfall(
        monkeypatch,
        {"src-1": "ORA", "tgt-2": "ORA"},
        {
            "tgt-2": {
                "scryfall_id": "tgt-2",
                "name": "Sol Ring",
                "set_code": "c21",
                "collector_number": "263",
            }
        },
    )

    repoint_inventory_row_printing(db, row_id=row.id, user_id=user.id, target_scryfall_id="tgt-2")
    db.refresh(row)

    new_card = db.query(Card).filter(Card.scryfall_id == "tgt-2").first()
    assert new_card is not None  # unknown target upserted
    assert row.card_id == new_card.id  # card_id changed in place
    logs = db.query(TransactionLog).filter(TransactionLog.inventory_row_id == row.id).all()
    assert len(logs) == 1
    assert logs[0].event_type == "repoint_printing"
    assert logs[0].quantity_delta == 0
    assert logs[0].card_id == new_card.id


def test_row_identity_and_references_survive(db, user, monkeypatch, row_reference_parents):
    refs = row_reference_parents
    loc = StorageLocation(user_id=user.id, name="Drawer 1", type="drawer", mode="managed")
    db.add(loc)
    db.flush()
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(
        db, user.id, old, storage_location_id=loc.id, drawer="1", slot="5", tags="x", notes="n"
    )
    row_id, created = row.id, row.created_at
    sc = ShowcaseItem(showcase_id=refs.showcase.id, inventory_row_id=row.id, quantity_offered=1)
    tr = TradeItem(
        trade_id=refs.trade.id,
        revision_id=refs.trade_revision.id,
        side="offer",
        inventory_row_id=row.id,
        quantity=1,
        finish="normal",
    )
    dcs = DeckCardShare(
        inventory_row_id=row.id,
        source_deck_id=refs.source_deck.id,
        target_deck_id=refs.target_deck.id,
        variant_group_id=refs.variant_group.id,
    )
    db.add_all([sc, tr, dcs])
    db.commit()
    _mock_scryfall(
        monkeypatch,
        {"src-1": "ORA", "tgt-2": "ORA"},
        {
            "tgt-2": {
                "scryfall_id": "tgt-2",
                "name": "Sol Ring",
                "set_code": "c21",
                "collector_number": "263",
            }
        },
    )

    repoint_inventory_row_printing(db, row_id=row.id, user_id=user.id, target_scryfall_id="tgt-2")
    db.refresh(row)

    assert row.id == row_id and row.created_at == created  # same row, not re-created
    assert (row.storage_location_id, row.drawer, row.slot, row.tags, row.notes) == (
        loc.id,
        "1",
        "5",
        "x",
        "n",
    )
    assert db.get(ShowcaseItem, sc.id).inventory_row_id == row.id
    assert db.get(TradeItem, tr.id).inventory_row_id == row.id
    assert db.get(DeckCardShare, dcs.id).inventory_row_id == row.id


def test_same_printing_is_noop(db, user, monkeypatch):
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, user.id, old)
    _mock_scryfall(monkeypatch, {"src-1": "ORA"}, {})

    repoint_inventory_row_printing(db, row_id=row.id, user_id=user.id, target_scryfall_id="src-1")
    db.refresh(row)

    assert row.card_id == old.id
    assert db.query(TransactionLog).filter(TransactionLog.inventory_row_id == row.id).count() == 0


def test_different_card_rejected(db, user, monkeypatch):
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, user.id, old)
    _mock_scryfall(
        monkeypatch,
        {"src-1": "ORA-ring", "bolt": "ORA-bolt"},
        {
            "bolt": {
                "scryfall_id": "bolt",
                "name": "Lightning Bolt",
                "set_code": "lea",
                "collector_number": "161",
            }
        },
    )

    with pytest.raises(ValueError, match="different card"):
        repoint_inventory_row_printing(
            db, row_id=row.id, user_id=user.id, target_scryfall_id="bolt"
        )
    db.refresh(row)
    assert row.card_id == old.id  # unchanged
    assert db.query(TransactionLog).filter(TransactionLog.inventory_row_id == row.id).count() == 0


def test_scryfall_target_failure_rejected(db, user, monkeypatch):
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, user.id, old)
    _mock_scryfall(monkeypatch, {"src-1": "ORA"}, {})  # target oracle → None (fetch failed)

    with pytest.raises(ValueError, match="not found on Scryfall"):
        repoint_inventory_row_printing(
            db, row_id=row.id, user_id=user.id, target_scryfall_id="tgt-2"
        )
    db.refresh(row)
    assert row.card_id == old.id


def test_owner_only(db, user, monkeypatch):
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, user.id, old)
    _mock_scryfall(monkeypatch, {"src-1": "ORA", "tgt-2": "ORA"}, {})

    with pytest.raises(InventoryRowNotFound):
        repoint_inventory_row_printing(
            db, row_id=row.id, user_id=user.id + 999, target_scryfall_id="tgt-2"
        )


def test_route_repoints(client, db, user, monkeypatch):
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, user.id, old)
    _mock_scryfall(
        monkeypatch,
        {"src-1": "ORA", "tgt-2": "ORA"},
        {
            "tgt-2": {
                "scryfall_id": "tgt-2",
                "name": "Sol Ring",
                "set_code": "c21",
                "collector_number": "263",
            }
        },
    )
    resp = client.post(
        f"/inventory/rows/{row.id}/repoint-printing",
        data={"scryfall_id": "tgt-2", "csrf_token": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(row)
    assert db.get(Card, row.card_id).scryfall_id == "tgt-2"


def test_route_different_card_is_400(client, db, user, monkeypatch):
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, user.id, old)
    _mock_scryfall(
        monkeypatch,
        {"src-1": "ORA-ring", "bolt": "ORA-bolt"},
        {
            "bolt": {
                "scryfall_id": "bolt",
                "name": "Lightning Bolt",
                "set_code": "lea",
                "collector_number": "161",
            }
        },
    )
    resp = client.post(
        f"/inventory/rows/{row.id}/repoint-printing",
        data={"scryfall_id": "bolt", "csrf_token": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_route_other_users_row_is_404(client, db, user, monkeypatch):
    from app.models import User

    other = User(username="other@example.com", password_hash="x")
    db.add(other)
    db.commit()
    old = _card(db, "src-1", "Sol Ring", "cmr", "1")
    row = _row(db, other.id, old)
    _mock_scryfall(monkeypatch, {"src-1": "ORA", "tgt-2": "ORA"}, {})
    resp = client.post(
        f"/inventory/rows/{row.id}/repoint-printing",
        data={"scryfall_id": "tgt-2", "csrf_token": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 404
