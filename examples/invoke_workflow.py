"""Run the small document-first workflow integration client.

This concise entry point and ``workflow_tester.py`` intentionally use the same
implementation so their retry, polling, and pagination behavior cannot drift.
Run with ``--help`` for authentication and request options.
"""

from workflow_tester import main

if __name__ == "__main__":
    raise SystemExit(main())
