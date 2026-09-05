from __future__ import annotations

from .errors import ScenarioError
from .models import ScheduledEvent, Scenario


def build_schedule(scenario: Scenario) -> list[ScheduledEvent]:
    events: list[ScheduledEvent] = []
    for item in scenario.timeline:
        if item.at_ms is not None:
            events.append(ScheduledEvent(item.at_ms, item.index, 0, item.action, item.payload))
            continue
        assert item.every_ms is not None and item.until_ms is not None
        occurrence = 0
        virtual_ms = item.every_ms
        while virtual_ms <= item.until_ms:
            events.append(ScheduledEvent(virtual_ms, item.index, occurrence, item.action, item.payload))
            occurrence += 1
            virtual_ms += item.every_ms
            if occurrence > 1_000_000:
                raise ScenarioError(f"timeline item {item.index} expands to too many events")
    return sorted(events, key=lambda event: (event.virtual_ms, event.timeline_index, event.occurrence))
