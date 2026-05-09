"""Load external-signals configuration from ``config/external_signals.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path("config/external_signals.yaml")


@dataclass
class ExternalSignalsConfig:
    channels: list[str] = field(default_factory=lambda: ["@JdubTrades_Telegram"])
    cadence: str = "daily"
    freshness_days: int = 7
    backfill_days: int = 30
    parser_model: str = "claude-haiku-4-5-20251001"

    @classmethod
    def load(cls, path: Path | str | None = None) -> ExternalSignalsConfig:
        p = Path(path) if path else _DEFAULT_CONFIG_PATH
        if not p.exists():
            return cls()
        with open(p) as fh:
            data = yaml.safe_load(fh) or {}
        valid_keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in valid_keys})
