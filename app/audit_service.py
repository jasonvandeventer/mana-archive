from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ImportBatch, TransactionLog


def create_import_batch(session: Session, filename: str, row_count: int, note: str | None = None) -> ImportBatch:
    batch = ImportBatch(filename=filename, row_count=row_count, note=note)
    session.add(batch)
    session.flush()
    return batch


def log_transaction(
    session: Session,
    event_type: str,
    card_id: int | None,
    finish: str | None,
    quantity_delta: int,
    source_location: str | None = None,
    destination_location: str | None = None,
    batch_id: int | None = None,
    inventory_row_id: int | None = None,
    note: str | None = None,
    flush: bool = False,
) -> TransactionLog:
    log = TransactionLog(
        event_type=event_type,
        card_id=card_id,
        finish=finish,
        quantity_delta=quantity_delta,
        source_location=source_location,
        destination_location=destination_location,
        batch_id=batch_id,
        inventory_row_id=inventory_row_id,
        note=note,
    )
    session.add(log)
    if flush:
        session.flush()
    return log


def list_transaction_logs(session: Session) -> list[TransactionLog]:
    return session.query(TransactionLog).order_by(TransactionLog.id.desc()).all()
