"""`runtime` command-line entry point. Subcommands (api, worker, ingest) arrive in later phases."""

import sys


def main() -> int:
    print("runtime: no subcommands yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
