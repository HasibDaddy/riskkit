# Publishing riskkit to PyPI

The package name `riskkit` is currently free on PyPI. Two ways to publish — the
automated one (recommended) and the manual one.

## Recommended: Trusted Publishing (no tokens)

This uses the included `.github/workflows/release.yml`. You configure PyPI once
to trust your GitHub repo, then publishing is just pushing a tag.

1. Create a PyPI account at https://pypi.org and verify your email.
2. Go to **Your projects → Publishing → Add a pending publisher** and enter:
   - PyPI project name: `riskkit`
   - Owner: `<your-github-username>`
   - Repository name: `riskkit`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. In your GitHub repo, create an environment named `pypi`
   (Settings → Environments → New environment).
4. Tag and push a release:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
   The workflow builds the package and publishes it. Done.

## Manual (one machine, with a token)

```bash
python -m pip install --upgrade build twine
python -m build                 # creates dist/*.whl and dist/*.tar.gz
python -m twine check dist/*
python -m twine upload dist/*    # paste a PyPI API token when prompted
```

## Before the first publish — checklist

- [x] GitHub handle (`HasibDaddy`) filled in across `pyproject.toml`,
      `mkdocs.yml`, `docs/`, and the workflow.
- [ ] Confirm `version` in `pyproject.toml` and `src/riskkit/__init__.py` match.
- [ ] `pytest` is green and CI passes on GitHub.
- [ ] `python -m build` succeeds locally and `twine check dist/*` passes.

## After publishing

- Verify the install: `pip install riskkit` in a clean venv.
- Bump the version for the next change (never re-upload the same version).
- Publish the docs: `mkdocs gh-deploy` (serves from the `gh-pages` branch).
