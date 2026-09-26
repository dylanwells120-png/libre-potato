"""Print a password hash for .env. The password itself is not saved."""

from __future__ import annotations

import getpass
import os
import sys

from app.passwords import PasswordHashError, hash_password


def main() -> None:
    password = os.environ.get("LIBRE_POTATO_PASSWORD", "")
    if password:
        print(
            "Reading LIBRE_POTATO_PASSWORD from the environment. Unset it when you are done.",
            file=sys.stderr,
        )
    else:
        password = getpass.getpass("New password: ")
        again = getpass.getpass("Repeat password: ")
        if password != again:
            raise SystemExit("Those passwords did not match.")
    try:
        print(hash_password(password))
    except PasswordHashError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
