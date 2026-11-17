# Phase H9 plan — A stronger sandbox

**Goal:** code the model writes runs behind a second wall. A bug in the Linux kernel is
no longer enough to escape it, and neither is a bug in sandboxd. You can see which wall
your install has, and an install that asked for the stronger one never quietly runs
without it.

**Why:**
- **The platform review's "make it competitive" list:** "a stronger sandbox (gVisor)".
- **CR-002 R13.9:** gVisor where it is available (SHOULD, not done).
- **CR-002 R13.4:** sandboxd uses the Docker socket only through a proxy that narrows it
  (MUST, not done on Compose: sandboxd mounts the raw socket, as root).
- **CR-002 AC22:** `make demo-sandbox-escape`, every escape attempt failing safely, PASS or
  FAIL each (not built).

| Gap | Today |
|---|---|
| The kernel | Every sandbox shares the host's kernel (runc). One kernel bug reachable from inside the container is an escape. |
| sandboxd | On Compose, it holds the raw Docker socket, as root, and listens on the internal network. Whoever controls it can start a privileged container with the host's disk mounted: root on the host. |
| Kubernetes | `runtimeClassName` is a Helm value nobody tests. kind and CI run runc. |
| Proof | SC2 in L6 checked the limits one by one. There's no escape suite, and nothing runs it on each change. |
| Honesty | Nothing tells you how strongly your code is isolated. |

## 1. Research (2026-11-11)

- **gVisor** (`runsc`) puts a kernel written in Go, in user space, between the code and the
  host. The code's system calls go to it, not to Linux; it calls the host through a small,
  filtered set. A host-kernel bug is then reachable only through gVisor's own bugs.
  - **Releases:** weekly, `release-20261102.0` the latest. x86_64 and arm64 tarballs, with
    `SHA512SUMS`. The tarball holds `runsc`, `containerd-shim-runsc-v1` and a `gvisor-bin/`
    folder that must sit next to `runsc`. Downloading missing pieces on first use ended in
    September 2026, so the install must be the whole tarball.
  - **Platform:** `systrap`, the default, runs inside a VM (Docker Desktop's, a CI
    runner's, a kind node's). KVM needs bare metal; `ptrace` is deprecated.
  - **Docker:** `runsc install` adds a `runsc` runtime to `daemon.json`; a container asks
    for it with `HostConfig.Runtime`. Linux hosts only, officially.
  - **Docker Desktop (macOS, Windows):** no supported way. A community method puts the
    binaries in a named volume (inside the VM) and registers the runtime; it doesn't
    always survive a settings change or an update.
  - **containerd / Kubernetes:** a `runsc` runtime in containerd's config
    (`io.containerd.runsc.v1`), and a `RuntimeClass` named `gvisor` with handler `runsc`.
    A Pod that asks for a RuntimeClass that doesn't exist is refused: Kubernetes fails
    closed by itself. GKE Sandbox is gVisor (`runtimeClassName: gvisor`); AKS's pod
    sandboxing is Kata, a microVM per Pod.
- **Costs to measure:** gVisor starts a little slower, and system calls (file I/O, `import
  pandas`) are slower.
- **Docker socket proxies** (Tecnativa, LinuxServer, wollomatic): they filter by method and
  path. They can allow `POST /containers/create`, but they don't read its body, so a
  create with `Privileged: true` and the host's `/` mounted passes. Filtering by path
  doesn't close our gap; the create body has to be checked.

### 1.1 The spike (2026-11-11): go, with four changes

gVisor `release-20261102.0` (arm64, checked against `SHA512SUMS`), run two ways:
- in a throwaway kind cluster on this Mac, with our sandbox Pod spec unchanged plus
  `runtimeClassName: gvisor`;
- through our real Docker adapter, against a separate Docker 29 daemon that has runsc,
  inside a container, so Docker Desktop stays untouched.

| | runc | gVisor |
|---|---|---|
| Kernel the code sees | the host's (`7.0.14-linuxkit`) | `4.19.0-gvisor`, and `dmesg` says "Starting gVisor..." |
| Non-root, read-only root, time limit (137), memory limit (137), workspace cap, no network, no service-account token | ✅ | ✅ |
| Start, then first exec (Docker) | 0.43 s | 0.32 s |
| Pod ready (kind) | 0.75 s | 0.76 s |
| `import pandas` | ~2.0–2.4 s | ~2.4–2.9 s |
| 50 new processes | 0.01 s | 0.21 s |

**What changes in the design:**
1. **Process limits under gVisor (Docker).** Docker's `PidsLimit: 64` counts host
   processes, and under gVisor each process inside needs a helper process on the host. A
   fork bomb then kills gVisor itself, and the sandbox with it: the next call gets "not
   running". At any host limit (1,024 too).
   - **The fix, measured:** the host limit becomes a generous bound on gVisor itself
     (512). The real limit, 64 processes, is `RLIMIT_NPROC`, enforced by gVisor's kernel,
     inside the sandbox. The bomb stops with "Resource temporarily unavailable", and the
     sandbox lives on.
   - **Never under runc:** there `RLIMIT_NPROC` counts the sandbox user's processes on the
     whole host, so one sandbox's bomb would block every other. runc keeps `PidsLimit: 64`.
2. **A bug, found on the way:** the Docker adapter pins API `v1.43`. Docker Engine 29
   refuses anything older than `1.44`, so the code tools fail on a Linux host with Docker
   29. Docker Desktop and CI's Docker 28 still accept it, which is why no test saw it. The
   adapter asks the daemon for its API version and uses that (at least 1.44).
3. **`unshare -r` works inside gVisor:** it makes a user namespace in gVisor's kernel, not
   the host's. The escape suite checks what an attempt can reach, not whether the call
   fails.
4. **Kubernetes, runc, today:** a fork bomb kills the sandbox container (probably its
   memory limit: 6,000 processes don't fit in 256 MB), even with `podPidsLimit: 4096`.
   Under gVisor the sandbox survived. The suite covers both; the run must get a clear error
   and a fresh sandbox on its next call.

Also seen: gVisor has its own network stack, but the deny-all NetworkPolicy (Kubernetes)
and `NetworkMode: none` (Docker) are still what keep the network out. gVisor doesn't
replace them.

## 2. Design

### 2.1 Isolation levels, and failing closed

One setting, `SANDBOX_ISOLATION`, for Compose and Kubernetes:

| Value | Meaning |
|---|---|
| `gvisor` | Every sandbox runs under gVisor. If it isn't available, sandboxd isn't ready: the code tools say "unavailable" and nothing runs in a weaker sandbox. |
| `container` | runc, as today. Locked down, but sharing the host's kernel. |
| `auto` | gVisor if this Docker (or cluster) has it, otherwise `container`, and it says which. |

- sandboxd reports its level on `/healthz` and `/readyz`. The API passes it on, and
  Settings → Tools shows it: "Code runs in gVisor (its own kernel)" or "Code runs in a
  container (it shares your computer's kernel)". Each Run Python card's details say the
  same.
- **Proof that it's real:** at start, and after any backend change, sandboxd runs a probe
  in a fresh sandbox and checks the kernel answers as gVisor's (`dmesg` from gVisor,
  `/proc/version`). A runtime that's only named `runsc` doesn't count.

### 2.2 gVisor on Compose

- **The Docker adapter** sets `HostConfig.Runtime: runsc` at the `gvisor` level. Everything
  else stays as it is: no network, read-only root, tmpfs, no capabilities, CPU and memory.
  The process limit moves inside, as the spike showed (1.1): `PidsLimit: 512` bounds gVisor
  itself, and `Ulimits: nproc 64` limits the code. Each control is re-checked under gVisor
  by the escape suite (2.5).
- **The API version:** asked of the daemon (`/version`), at least 1.44 (1.1, the bug).
- **`./setup.sh --gvisor`:**
  - **Linux:** downloads the pinned release for this machine, checks it against
    `SHA512SUMS`, installs it to `/usr/local/bin` (asking for sudo, saying why), runs
    `runsc install` and restarts Docker. It sets `SANDBOX_ISOLATION=gvisor`.
  - **Docker Desktop:** prints the steps, with a warning that Docker doesn't support them
    and may undo them. It doesn't change Docker Desktop's settings itself.
- **Default:** `auto`. Nothing changes for an install that doesn't have gVisor, except
  that it now says what it has.

### 2.3 sandboxd no longer holds the socket (Compose)

A new small service, **`sandbox-gate`**, is the only one with the Docker socket. It
listens on its own internal network, which only sandboxd joins, behind sandboxd's token.
- **It checks every create body (Specification):** the sandbox image, our labels, a
  non-root user, no network, read-only root, our two tmpfs mounts and nothing else
  mounted, every capability dropped, `no-new-privileges`, the limits within the
  configured ones, and `Runtime: runsc` at the `gvisor` level. Anything else is refused,
  and an unknown field counts as anything else.
- **The other calls:** start, exec, inspect, list and delete are allowed only for
  containers that carry our label. `/exec/{id}/start` is allowed only for an exec the gate
  created.
- **Who runs as what:**
  - the gate runs as root, with no other network, and has no code from outside it;
  - sandboxd runs as an unprivileged user, holding nothing root-equivalent.
- **The cost:** a compromised sandboxd can still start sandboxes. It can't start anything
  else, and it can't touch Postgres, the model keys or the host.

### 2.4 gVisor on Kubernetes

- **kind (`./setup.sh --kubernetes`, CI):** the cluster is created with runsc in its node
  (the tarball, mounted into the node, and a containerd config patch), plus a
  `RuntimeClass` `gvisor`. The chart gets `sandbox.isolation: gvisor`.
- **The chart:**
  - `sandbox.isolation` replaces `runtimeClassName`, which stays as an override. Kata on
    AKS, for example, is `runtimeClassName: kata-vm-isolation`.
  - `sandbox.createRuntimeClass` covers kind only; managed clusters ship their own.
- **The Kubernetes adapter:** reads its level the same way, and its probe checks it too.

### 2.5 The escape suite (AC22): `make demo-sandbox-escape`

Each attempt runs as model code through `run_python`, and each prints PASS or FAIL. It runs
on Compose and on kind, at both levels, and prints the level it ran at.
- **Filesystem:**
  - write to `/`, `/etc`, `/usr`;
  - read the host's files, the Docker socket, `/proc/1/root` outside;
  - fill `/workspace` past its cap.
- **Privilege:**
  - setuid, `sudo` and `su`;
  - `mount` and `unshare`;
  - `ptrace` another process;
  - load a kernel module;
  - `/proc/sysrq-trigger`.
- **Network:** the internet (`1.1.1.1`), Postgres, Redis, sandboxd, the gate, the API, and
  cloud metadata (`169.254.169.254`). Kubernetes' API server too.
- **Resources:** a fork bomb, a memory bomb and a busy loop. Meanwhile, the worker and
  another run's sandbox keep answering.
- **Secrets:** no environment variables beyond ours, and no service-account token.
- **Other runs:** a run can't see or reach another run's sandbox.
- **The kernel:** at `gvisor`, `uname` and `dmesg` are gVisor's. At `container`, the suite
  says plainly that the host kernel is shared.
- **The gate (Compose):** called the way a compromised sandboxd would call it: a
  privileged create, a host mount, host networking, another image, someone else's
  container. Each is refused.

### 2.6 Measuring the cost

Through the app, at each level, 20 times each:
- the first Run Python of a turn (cold start);
- `print(1)`;
- `import pandas`;
- a 50 MB write and read in `/workspace`.

The results go in the summary, with the trade-off spelled out.

## 3. Tasks

0. ~~A spike, first (go/no-go)~~: done, go (1.1).
1. The Docker API version fix, with a test that fails on 1.43.
2. `SANDBOX_ISOLATION`, the probe, the readiness rule; both adapters; the process limit
   inside gVisor.
3. `sandbox-gate`: the create Specification, the label rule, the exec rule. sandboxd as a
   non-root user. Compose networks.
4. `setup.sh --gvisor` (Linux) and the Docker Desktop instructions; `--doctor` reports the
   level.
5. kind with gVisor; the chart values; CI's kind job at `gvisor`.
6. The escape suite, on Compose and kind, in CI.
7. Settings → Tools and the card's details show the level; the API field and its types.
8. The cost measurements.
9. Docs: `docs/security.md` (what each level protects against, and what it doesn't), the
   README, ADR 0007, `docs/design.md`, the CHANGELOG.
10. The sandbox follows the newest epoch: an older epoch gets 409 and the worker stops
    (from the external review of 2026-11-12, H10 2.4).

## 4. Success criteria

| # | Criterion |
|---|---|
| 1 | At `gvisor`, every sandbox's kernel is gVisor's (the probe), on Compose (Linux CI) and kind (CI and this Mac) |
| 2 | At `gvisor` without gVisor, nothing runs: sandboxd isn't ready, and the tools say so |
| 3 | The escape suite passes at both levels, on Compose and kind, in CI |
| 4 | sandboxd has no Docker socket and runs as non-root; the gate refuses every create that isn't our sandbox |
| 5 | Settings → Tools and the card show the level, truthfully at each level |
| 6 | The cost is measured, and Run Python's cold start at `gvisor` stays under 3 s at p95 on CI |
| 7 | Quality bar: backend, runtime e2e × 5, container e2e, browser, UI, ruff, mypy `--strict`, and the existing L6 sandbox scenarios at both levels |
| 8 | An older epoch can't remove a newer sandbox: 409, the stale worker's call ends as fenced, the new owner's workspace is intact |

## 5. Out of scope

- **MicroVMs** (Firecracker, Kata) on Compose. Kata is documented for AKS through the
  `runtimeClassName` override, not tested.
- **The warm pool** (R13.9's other half).
- **`fetch_url` through an egress allowlist** (R13.8).
- **gVisor on Docker Desktop done by setup itself:** Docker doesn't support it.
- **Skills that run scripts** (P13).
