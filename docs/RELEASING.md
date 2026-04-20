# Releasing `manifoldbt-mcp`

This repo publishes to [PyPI](https://pypi.org/project/manifoldbt-mcp/) and
[TestPyPI](https://test.pypi.org/project/manifoldbt-mcp/) through [PyPI
Trusted Publishing](https://docs.pypi.org/trusted-publishers/), so **no API
tokens are stored in GitHub**.

## One-time setup

You need to do this **once per PyPI account**.

### 1. TestPyPI

1. Go to <https://test.pypi.org/manage/account/publishing/>
2. "Add a new pending publisher" (or add it on the existing project once it
   exists):
   - **PyPI Project Name**: `manifoldbt-mcp`
   - **Owner**: `ClementG91`
   - **Repository name**: `manifoldbt-mcp`
   - **Workflow name**: `release.yml`
   - **Environment name**: `testpypi`
3. Save.

### 2. PyPI

1. Go to <https://pypi.org/manage/account/publishing/>
2. Add a pending publisher with the same values, but **Environment name**
   = `pypi`.

### 3. GitHub environments

In your repo → Settings → Environments → create two environments:

- `testpypi`
- `pypi`

No secrets needed. Optionally, add a required reviewer on `pypi` so
publishing waits for a manual approval.

---

## Cutting a release

1. Bump `version` in [`pyproject.toml`](../pyproject.toml) (and
   `__version__` in `src/manifoldbt_mcp/__init__.py` if you keep them in
   sync).
2. Commit and merge to `main`.
3. Tag and push:

   ```bash
   git tag -a v0.1.0 -m "v0.1.0"
   git push origin v0.1.0
   ```

4. The [`Release`](../.github/workflows/release.yml) workflow runs:
   - Verifies the tag matches the `pyproject.toml` version.
   - Builds sdist + wheel.
   - Publishes to TestPyPI.
   - Publishes to PyPI.
   - Attaches the artifacts to a GitHub Release with auto-generated notes.

You can also trigger the workflow manually from the Actions tab with the
`workflow_dispatch` input (`tag`: an existing tag like `v0.1.0`).
