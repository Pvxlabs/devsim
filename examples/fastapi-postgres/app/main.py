from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .db import EventRecord, NotificationRecord, SessionLocal, SessionRecord

app = FastAPI(title="DevSim FastAPI example")


class EventInput(BaseModel):
    type: str
    session_id: int | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/demo/state")
def state() -> dict[str, list[dict[str, object]]]:
    with SessionLocal() as db:
        sessions = db.scalars(select(SessionRecord).order_by(SessionRecord.id)).all()
        events = db.scalars(select(EventRecord).order_by(EventRecord.id)).all()
        notifications = db.scalars(select(NotificationRecord).order_by(NotificationRecord.id)).all()
        return {
            "sessions": [{"id": item.id, "name": item.name, "status": item.status} for item in sessions],
            "events": [{"id": item.id, "type": item.event_type, "status": item.status} for item in events],
            "notifications": [{"id": item.id, "message": item.message, "status": item.status} for item in notifications],
        }


@app.post("/api/demo/events", status_code=201)
def create_event(payload: EventInput) -> dict[str, object]:
    with SessionLocal() as db:
        session = db.get(SessionRecord, payload.session_id) if payload.session_id else db.scalar(select(SessionRecord).limit(1))
        if session is None:
            raise HTTPException(status_code=409, detail="no session exists")
        event = EventRecord(session_id=session.id, event_type=payload.type, status="processing")
        session.status = "active"
        db.add(event)
        db.add(NotificationRecord(message=f"Event {payload.type} is processing", status="created"))
        db.commit()
        db.refresh(event)
        return {"id": event.id, "session_id": event.session_id, "type": event.event_type, "status": event.status}


@app.post("/api/demo/heartbeat")
def heartbeat() -> dict[str, object]:
    with SessionLocal() as db:
        pending = db.scalars(select(EventRecord).where(EventRecord.status == "processing")).all()
        for event in pending:
            event.status = "completed"
            db.add(NotificationRecord(message=f"Event {event.event_type} completed", status="created"))
        db.commit()
        return {"completed_events": len(pending)}
