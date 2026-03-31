import logging


class SafeStreamHandler(logging.StreamHandler):
    """Stream handler that degrades gracefully when terminal encoding cannot print Unicode."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                message = self.format(record)
                stream = self.stream
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe_message = message.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
                stream.write(safe_message + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)
