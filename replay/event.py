"""Core event type shared across ingest and replay modules.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    type: str
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        """Shape sent over the WebSocket -- timestamp as ISO string
        since datetime isn't directly JSON-serializable."""
        return {
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }
