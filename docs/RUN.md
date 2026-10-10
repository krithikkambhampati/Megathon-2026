# Running the project

> Owned by P5. The full clean-machine instructions (data, training, Ollama, demo) are added later.
> For now this covers setup and the dependency rules.

## Quick setup
1. Install uv (≥ 0.4): `pip install --user uv` or the official installer at https://docs.astral.sh/uv/.
2. Clone the repo and `cd` into it.
3. `make setup`. This installs Python 3.11 (if needed) and every pinned package from `uv.lock` into `.venv`.
4. `make test` should pass.

Run every Python command through `uv run …` (or a `make` target), never with a system `python`.

## Dependencies

**Only the P5 owner adds, removes or upgrades packages.** Everyone shares one `pyproject.toml` and one
`uv.lock`. If five people run `uv add` on their own, the lockfile breaks on every merge.

### If you need a package
1. Post in the team channel:
   `DEP REQUEST: <package> (<version if it matters>), needed by P<n> for <one-line reason>`.
2. P5 adds it within **30 minutes**, pins the exact version, runs `make test`, and pushes a commit to `main`
   titled `deps: add <package> (P<n>)`.
3. Merge `main` into your branch, then run `make setup` (or `uv sync`).

### Rules
- **Don't** run `uv add`, `uv remove`, `uv lock --upgrade` or `pip install` in this project.
- **Don't** edit `uv.lock` by hand.
- Versions in `pyproject.toml` are **exact pins** (`==`). Nobody upgrades during the event.
- Test and lint tools go in the `dev` dependency group. STRETCH-only packages (for example `shap`) go in
  the `stretch` extra (`uv sync --extra stretch`).
- **Merge conflict in `uv.lock`?** Take `main`'s version of both `pyproject.toml` and `uv.lock`, and send
  P5 a request for anything your branch added.
- After any pull that changes `uv.lock`, run `make setup` before anything else.

### For P5: adding a dependency
```
uv add "<package>==<exact version>"        # or: uv add --group dev "<package>==<version>"
make test && make lint
git add pyproject.toml uv.lock
git commit -m "deps: add <package> (P<n>)"
git push origin main
```
Then reply to the request in the channel with the commit hash.
