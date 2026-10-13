"""End-to-end scenarios: real API and worker *processes* on real Postgres and Redis.

Each scenario doubles as a demo: `make demo-crash` / `demo-zombie` /
`demo-release` run them and print PASS/FAIL per check; pytest runs the same
functions (tests/e2e/test_scenarios.py).
"""
