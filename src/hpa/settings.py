"""What a running server is allowed to do, read from the environment.

Locally nothing is set and the server behaves as it always has: live runs for anyone who
can reach it, no caps. The hosted demo sets these, which is where SPEC's "Hosted demo
constraints" live: a shared password for live scans, a per-IP rate limit, a cap on how many
price files one run may download, and a daily budget for model calls.
"""

import os
from dataclasses import dataclass

TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    live_pin: str | None = None  # HPA_LIVE_PIN: required to start a live run when set
    runs_per_hour: int | None = None  # HPA_RUNS_PER_HOUR: live runs per IP
    max_downloads: int | None = None  # HPA_MAX_DOWNLOADS: new files one run may fetch
    daily_cap_usd: float | None = None  # HPA_DAILY_CAP_USD: model spend per day
    keep_downloads: bool = True  # HPA_KEEP_DOWNLOADS=0: delete the raw file after extraction
    trust_proxy: bool = False  # HPA_TRUST_PROXY=1: take the client IP from X-Forwarded-For
    require_pin: bool = False  # HPA_REQUIRE_PIN=1: refuse to serve at all without a PIN (a public host)

    @property
    def live_needs_pin(self) -> bool:
        return bool(self.live_pin)

    def check(self) -> None:
        """Raise if this configuration must not be served: a host that requires a password
        and has none would otherwise open live scans, and the model budget, to anyone."""
        if self.require_pin and not self.live_pin:
            raise ValueError("HPA_REQUIRE_PIN is set but HPA_LIVE_PIN (the live-scan password) is empty: "
                             "refusing to serve live scans to anyone")


def _int(env, name: str) -> int | None:
    value = env.get(name)
    return int(value) if value not in (None, "") else None


def _float(env, name: str) -> float | None:
    value = env.get(name)
    return float(value) if value not in (None, "") else None


def _bool(env, name: str, default: bool) -> bool:
    value = env.get(name)
    return default if value in (None, "") else value.strip().lower() in TRUE


def from_env(env=None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        live_pin=(env.get("HPA_LIVE_PIN") or "").strip() or None,
        runs_per_hour=_int(env, "HPA_RUNS_PER_HOUR"),
        max_downloads=_int(env, "HPA_MAX_DOWNLOADS"),
        daily_cap_usd=_float(env, "HPA_DAILY_CAP_USD"),
        keep_downloads=_bool(env, "HPA_KEEP_DOWNLOADS", True),
        trust_proxy=_bool(env, "HPA_TRUST_PROXY", False),
        require_pin=_bool(env, "HPA_REQUIRE_PIN", False),
    )
