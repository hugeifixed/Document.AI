#!/usr/bin/env python3
"""Install an approved Scalar npm tarball as Django static files, without network access.

Only the self-contained browser bundle is needed, not Scalar's build dependencies.
The pinned tarball integrity is checked before reading an explicitly named member;
no archive paths are extracted onto the filesystem. Run before collectstatic/build.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import tarfile
from pathlib import Path

VERSION = "1.68.0"  # Published 2026-09-07; admitted after the seven-day waiting period.
INTEGRITY = (
    "rY43w3REwCxp+rDDx/0CncZxmlzISnGTK9zZ8moq0Ij2vRHhLQCJ0/BXut9pBAupVrOZF7MoqKXcG+gISgTu5g=="
)
DESTINATION = (
    Path(__file__).resolve().parents[1]
    / "backend/docai/static/docai/vendor/scalar"
    / VERSION
    / "standalone.js"
)


def install(package: Path, destination: Path = DESTINATION) -> None:
    with package.open("rb") as stream:
        digest = base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode("ascii")
        if digest != INTEGRITY:
            raise ValueError(
                f"Expected the unmodified @scalar/api-reference@{VERSION} npm tarball."
            )
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            member = archive.getmember("package/dist/browser/standalone.js")
            if not member.isfile():
                raise ValueError("Scalar's standalone bundle must be a regular file.")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Scalar's standalone bundle is missing.")
            bundle = source.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(bundle)
    temporary.replace(destination)
    license_file = Path(__file__).resolve().parents[1] / "docs/licenses/scalar-MIT.txt"
    destination.with_name("LICENSE.txt").write_bytes(license_file.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help=f"Path to scalar-api-reference-{VERSION}.tgz")
    args = parser.parse_args()
    try:
        install(args.package)
    except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
        parser.exit(1, f"Scalar asset installation failed: {exc}\n")
    print(f"Installed Scalar {VERSION} to {DESTINATION}")


if __name__ == "__main__":
    main()
