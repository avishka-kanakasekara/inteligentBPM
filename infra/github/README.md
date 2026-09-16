# CI/CD (native, no containers)

GitHub Actions workflow: `../../.github/workflows/ci.yml`

Jobs use:

- `actions/setup-python` + pip/venv style installs
- `actions/setup-node` + npm

No Docker build/push jobs.
