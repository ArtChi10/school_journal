#!/usr/bin/env python
import os
import sys

def _configure_windows_utf8_stdio() -> None:
    """Force UTF-8 console streams so non-ASCII log lines do not crash on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")

def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.settings")
    _configure_windows_utf8_stdio()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and available on your "
            "PYTHONPATH environment variable? Did you forget to activate a virtual "
            "environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()