"""DB wrapper that materializes candidate event facts from artifact refs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.quant_sim.lifecycle_artifact_adapter import candidate_artifact_payload


class ArtifactBackedCandidateEventDB:
    """Delegate QuantSimDB calls while keeping candidate event rows light.

    QuantUniverseManager expects event payloads to contain technical facts for
    gate/scoring. For drill/replay flows those facts must come from the
    run-scoped artifact store, not from persisted candidate event payloads.
    """

    def __init__(self, db: Any, *, artifact_db_file: str | Path) -> None:
        self._db = db
        self._artifact_db_file = artifact_db_file

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)

    def add_candidate_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = self._db.add_candidate_event(payload)
        return self._with_artifact_payload(event)

    def list_candidate_events(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        events = self._db.list_candidate_events(*args, **kwargs)
        return [self._with_artifact_payload(event) for event in events]

    def _with_artifact_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload_json") if isinstance(event.get("payload_json"), dict) else {}
        artifact_payload = candidate_artifact_payload(payload, db_file=self._artifact_db_file)
        return {**event, "payload_json": {**payload, **artifact_payload}}
