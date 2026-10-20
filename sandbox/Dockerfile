# syntax=docker/dockerfile:1.7
# The sandbox (phase L6b, CR-002 §13): where Run Python, the terminal and the workspace
# files run, one container per run, started by sandboxd.
#
#   Python 3.12 with a few common data libraries, bash and coreutils; no compilers, no
#   network tools (the container has no network anyway), no secrets; a non-root user.
#   The container itself is locked down by sandboxd: read-only root, tmpfs workspace,
#   no network, CPU/memory/process limits, all capabilities dropped.

ARG PYTHON_IMAGE=python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
FROM ${PYTHON_IMAGE}

RUN pip install --no-cache-dir --disable-pip-version-check \
        numpy==2.3.4 pandas==2.3.3 python-dateutil==2.9.0.post0 tabulate==0.9.0 \
    && pip uninstall -y pip setuptools wheel 2>/dev/null; \
    find /usr/local/lib/python3.12 -depth \( -name tests -o -name __pycache__ \) -type d \
        -exec rm -rf {} + ; \
    useradd --uid 10002 --create-home --shell /bin/bash sandbox \
    && mkdir -p /workspace && chown sandbox:sandbox /workspace

USER 10002
WORKDIR /workspace
ENV HOME=/workspace PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp
CMD ["sleep", "infinity"]
