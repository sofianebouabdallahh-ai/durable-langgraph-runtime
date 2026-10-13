"""`python -m tests.e2e <scenario> [--repeat N]`: run e2e scenarios as demos.

Prints PASS/FAIL per check and exits non-zero on any failure (used by
`make demo-crash`, `demo-zombie`, `demo-release`, `demo-e2e`).
"""

import argparse
import asyncio
import sys

from tests.e2e.scenarios import SCENARIOS, run_scenario

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.e2e")
    parser.add_argument("scenario", choices=[*SCENARIOS, "all"])
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    failures = 0
    for i in range(args.repeat):
        for name in names:
            report, logs = asyncio.run(run_scenario(name))
            suffix = f" (run {i + 1}/{args.repeat})" if args.repeat > 1 else ""
            print(f"\n== {report.scenario}{suffix}")
            for check, ok, detail in report.checks:
                mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
                print(f"  {mark}  {check}" + (f"  [{detail}]" if detail else ""))
            print(f"  => {GREEN + 'PASS' if report.passed else RED + 'FAIL'}{RESET}")
            if not report.passed:
                failures += 1
                print(logs)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
