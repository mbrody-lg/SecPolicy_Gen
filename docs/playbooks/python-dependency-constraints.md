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

## Python Support And EOL

The canonical lifecycle contract is `.github/python-support-policy.json`:

- Python 3.11 is the reproducible service-container baseline.
- Python 3.11 is currently the only fully supported application runtime.
- Python 3.12 through 3.14 are required tooling-compatibility targets for
  upcoming runtime promotion; passing lint alone is not a support claim.
- Python 3.15 is preview-only and must not block pull requests before stable
  release and dependency compatibility evidence.

Start migration work when a supported version enters the 180-day EOL warning
window. An upstream EOL version cannot be introduced into new configuration
and must be removed from required CI, documentation, images, and developer
bootstrap paths within 30 days. Runtime promotion requires fresh constraints,
service tests, clean amd64/arm64 images, and critical-path evidence before the
Docker baseline changes.
