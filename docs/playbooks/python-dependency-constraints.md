# Python Dependency Constraints

The three Python services keep direct dependency intent in `requirements.txt`
and the complete Python 3.11 resolution in `constraints-py311.txt`. Docker
builds must install both files together and finish with `pip check`.

## Update Contract

1. Update one dependency family in a dedicated compatibility branch.
2. Resolve the complete graph in a clean Python 3.11 Linux container.
3. Review direct and transitive changes before replacing the service constraint
   file.
4. Run `make python-constraints-check` and the affected service tests.
5. Build the affected image for both `linux/amd64` and `linux/arm64` before
   merge. Record an unavailable architecture as a blocker, not as passing
   evidence.

Do not combine OpenAI, Mistral, model-runtime, or Torch upgrades unless the PR
explicitly owns and tests that compatibility change. Policy Agent must install
its exact `+cpu` Torch build from `https://download.pytorch.org/whl/cpu` before
resolving the remaining constrained requirements.

The current constraint files were captured from the service images that passed
the full functional smoke on 2026-09-22. They establish the reproducible
baseline; they are not a claim that every captured version is the preferred
long-term version.
