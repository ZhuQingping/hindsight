"""Customer console diagnostics; internal sinks receive the untouched record."""

import copy
import logging

from .public_errors import public_error_message


class PublicLogFormatter(logging.Formatter):
    """Avoid leaking implementation modules and stacks through local-engine output."""

    def __init__(self, delegate: logging.Formatter) -> None:
        super().__init__()
        self.delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        public = copy.copy(record)
        public.name = record.name.replace("hindsight_api", "agentstratum").replace("hindsight.", "agentstratum.")
        public.msg = public_error_message(record.getMessage())
        public.args = ()
        if record.exc_info and record.exc_info[1]:
            public.msg += ": " + public_error_message(record.exc_info[1])
        public.exc_info = None
        public.exc_text = None
        public.stack_info = None
        return self.delegate.format(public)
