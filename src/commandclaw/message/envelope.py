from __future__ import annotations

import time
from dataclasses import dataclass, field

_VALID_MESSAGE_TYPES = {"user", "control", "server"}


@dataclass(frozen=True)
class MsgEnvelope:
    session_id: str
    content: str
    message_type: str
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.message_type not in _VALID_MESSAGE_TYPES:
            raise ValueError(
                f"message_type must be one of {_VALID_MESSAGE_TYPES!r}, got {self.message_type!r}"
            )
