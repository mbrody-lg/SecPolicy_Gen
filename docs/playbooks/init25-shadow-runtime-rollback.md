# INIT-25 Shadow Runtime Rollback

The INIT-25 shadow runtime is default-off. Run it only as an explicit,
time-bounded operator action; do not install it as a service, scheduler, or
automatic retry. Shadow output is non-authoritative and must never update the
authoritative services, databases, queues, policy state, or validation state.

## Before A Run

1. Confirm the authoritative services are ready and record their container
   identity, start time, and restart count:

   ```bash
   curl -fsS http://localhost:5003/health
   curl -fsS http://localhost:5003/ready
   curl -fsS http://localhost:5002/health
   curl -fsS http://localhost:5002/ready
   curl -fsS http://localhost:5001/health
   curl -fsS http://localhost:5001/ready
   docker inspect -f '{{.Id}} {{.State.StartedAt}} {{.RestartCount}}' context_agent_web policy_agent_service validator_agent_service
   ```

2. Use a new output directory and a finite `--timeout`. Keep the authoritative
   summary read-only. Do not run against an output directory from an earlier
   attempt.

## Rollback Triggers

Rollback and pause on any timeout, signal, non-zero runner exit, unverified log
reference, runtime or security error, or parity recommendation of `pause`.
Treat `sbx_unavailable` as fail-closed: do not fall back to an unsandboxed
command, direct provider call, simulation presented as live evidence, or an
automatic retry. Restore sandbox availability, obtain a fresh operator
approval, and start a new run.

## Rollback Procedure

1. Stop the shadow runner. The adapter starts each Docker Agent invocation in
   its own process group and terminates that entire group on completion or
   timeout. If an invocation remains, identify its exact PID and PGID before
   acting:

   ```bash
   ps -axo pid,ppid,pgid,command | grep '[d]ocker agent run'
   ps -o pid=,ppid=,pgid=,command= -p <PID>
   kill -TERM -- -<PGID>
   sleep 5
   ps -o pid=,ppid=,pgid=,command= -g <PGID>
   kill -KILL -- -<PGID>  # only if the confirmed group remains
   ```

   Never use a broad `pkill`, and never target a PGID containing the operator
   shell or an authoritative service.

2. Preserve only bounded evidence already emitted in the run output directory:
   `authoritative-summary.json`, `candidate-summary.json`, `parity-report.json`,
   and the metadata-only `runtime-logs/*.jsonl` files referenced by the
   candidate summary. Record file sizes and SHA-256 digests, then make the
   evidence read-only:

   ```bash
   find <OUTPUT_DIR> -type f \( -name 'authoritative-summary.json' -o -name 'candidate-summary.json' -o -name 'parity-report.json' -o -path '*/runtime-logs/*.jsonl' \) -exec wc -c {} \;
   find <OUTPUT_DIR> -type f \( -name 'authoritative-summary.json' -o -name 'candidate-summary.json' -o -name 'parity-report.json' -o -path '*/runtime-logs/*.jsonl' \) -exec shasum -a 256 {} \;
   chmod -R a-w <OUTPUT_DIR>
   ```

   Do not preserve prompts, raw stdout or stderr, provider payloads, full
   environment dumps, secrets, database exports, or unbounded service logs.

3. Leave authoritative state untouched. Do not run `make down`, rebuild or
   restart containers, replay requests, call mutating endpoints, drain queues,
   edit databases, or promote/copy shadow artifacts into authoritative paths.

4. Repeat the read-only `/health`, `/ready`, and `docker inspect` commands from
   **Before A Run**. All endpoints must return success, and each container ID,
   start time, and restart count must match the pre-run record. A mismatch is an
   authoritative-service incident: keep shadow mode off, preserve the bounded
   evidence, and escalate without attempting repair from this playbook.

5. Record the run as `paused`, including the case ID, correlation ID, trigger,
   runner exit code, evidence digests, and verification result. A later run
   requires a new output directory and explicit operator action; rollback never
   resumes or retries shadow execution.
