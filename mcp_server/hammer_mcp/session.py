"""Connection ownership and process-local address caches, scoped to a session."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading
from .settings import DEFAULT_PIPE
from .transport import Cs2Pipe

@dataclass
class AddressCache:
    hammer_base: int | None = None
    tool_modules: dict[str, dict] = field(default_factory=dict)
    qt_menus: dict[str, tuple[int, int]] = field(default_factory=dict)
    dm_table: list[int] | None = None
    dm_table_key: tuple[int, ...] = ()
    symbol_names: dict[int, str] = field(default_factory=dict)

class BridgeSession:
    def __init__(self, pipe_name: str = DEFAULT_PIPE):
        self.cache = AddressCache()
        self.lock = threading.RLock()
        self.pipe = Cs2Pipe(pipe_name, on_reset=self.invalidate_caches)

    def invalidate_caches(self) -> None:
        self.cache = AddressCache()

    @contextmanager
    def activate(self):
        # Keep each multi-call editing operation together, including nested calls.
        with self.lock:
            token = _current.set(self)
            try:
                yield self
            finally:
                _current.reset(token)

    def close(self) -> None:
        with self.lock:
            self.pipe.close()
            self.invalidate_caches()

_default = BridgeSession()
_current: ContextVar[BridgeSession | None] = ContextVar("hammer_session", default=None)

def get_session() -> BridgeSession:
    return _current.get() or _default

def configure_default(pipe_name: str = DEFAULT_PIPE) -> BridgeSession:
    global _default
    _default.close()
    _default = BridgeSession(pipe_name)
    return _default
