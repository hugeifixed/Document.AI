#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    # Tests must not inherit an institution's Oracle/local database profile.
    # Django still honors an explicit --settings override for integration testing.
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
