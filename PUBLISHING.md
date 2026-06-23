# Publishing riskkit to PyPI

**Status (2026-06-23):** v0.4.0 is **build-verified and ready to publish** —
`python -m build` succeeds, `twine check` passes, and a clean-venv install of the
wheel imports and runs the full v0.4 surface (core is zero-dependency). The only
steps left are the PyPI-account ones below.

**Distribution name:** `riskkit-trading`. The ideal `riskkit` is unregistered (API
404) but PyPI's pending-publisher form rejects it as **too similar to the existing
`risk-kit`**, so the distribution name is `riskkit-trading` (free, more distinct).
The *import* name is unchanged: `pip install riskkit-trading` then `import riskkit`
— exactly like `scikit-learn` → `import sklearn`. If the form ever rejects
`riskkit-trading` too, `riskkit-quant` and `pyriskkit` are also free; change only
`name` in `pyproject.toml` to match. Never re-upload a version once published.

Two ways to publish — the automated one (recommended) and the manual one.

## Recommended: Trusted Publishing (no tokens)

This uses the included `.github/workflows/release.yml`. You configure PyPI once
to trust your GitHub repo, then publishing is just pushing a tag.

1. Create a PyPI account at https://pypi.org and verify your email.
2. Go to **Your projects → Publishing → Add a pending publisher** and enter:
   - PyPI project name: `riskkit-trading`
   - Owner: `HasibDaddy`
   - Repository name: `riskkit`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. In your GitHub repo, create an environment named `pypi`
   (Settings → Environments → New environment).
4. Tag and push a release:
   ```bash
   git tag v0.4.0
   git push origin v0.4.0
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
- [x] `version` matches in `pyproject.toml` and `src/riskkit/__init__.py` (`0.4.0`).
- [x] `pytest` green (118 tests) and CI passes on GitHub across Python 3.9–3.12.
- [x] `python -m build` succeeds and `twine check dist/*` passes; the wheel installs
      and imports cleanly in a fresh venv with zero dependencies.

## After publishing

- Verify the install: `pip install riskkit-trading` in a clean venv (then `import riskkit`).
- Update the README install line from the GitHub URL to `pip install riskkit-trading`.
- Bump the version for the next change (never re-upload the same version).
- Docs are already live at https://hasibdaddy.github.io/riskkit/ (re-run
  `mkdocs gh-deploy` after docs changes).
