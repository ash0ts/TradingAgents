"""Optional private OTLP journal for exact recovery after native export loss.

Stores already-ended spans, including original IDs, parent IDs and timestamps.
No provider patching, network traffic or second model instrumentation is added.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.trace import SpanProcessor

logger = logging.getLogger(__name__)


class TraceJournal(SpanProcessor):
    def __init__(self, directory, project):
        entity, separator, name = project.partition("/")
        if not separator or any(x in {"", ".", ".."} for x in (entity, name)) or "/" in name:
            raise ValueError("Journal project must be entity/project")
        self.directory = Path(directory) / entity / name
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._failed = False
        self._lock = Lock()

    def on_end(self, span):
        temporary = None
        try:
            identity = f"{span.context.trace_id:032x}-{span.context.span_id:016x}"
            target = self.directory / (identity + ".otlp")
            temporary = target.with_suffix("." + uuid4().hex + ".tmp")
            payload = encode_spans([span]).SerializeToString()
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        except Exception:
            with self._lock:
                self._failed = True
            logger.exception("Could not journal an Agent Lens span; native export continues")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove an incomplete trace journal file")

    def force_flush(self, timeout_millis=30000):
        # Native force_flush only drains its queue; it cannot prove delivery.
        with self._lock:
            return not self._failed
