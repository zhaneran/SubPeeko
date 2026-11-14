# Build and package SubPeeko

The project requires Python 3.10 or later. Build commands should run from the
repository root.

## Prepare a build environment

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install --upgrade build twine
```

Install the project and its runtime dependencies when running the command-line
tool locally.

```bash
python -m pip install -e .
```

## Run checks

```bash
python -m pip check
python -m unittest discover -s tests -v
```

The test suite uses synthetic model responses and does not require an API key.

## Build artifacts

```bash
python -m build
python -m twine check dist/*
```

The build creates a wheel and a source distribution in `dist/`. The custom
build step checks the upstream vocabulary revision and license. When the
upstream check is unavailable, it keeps the bundled vocabulary snapshot and
reports the fallback. It does not fetch vocabulary at runtime.

Inspect the contents before publishing.

```bash
python -c "import zipfile; print(zipfile.ZipFile('dist/subpeeko-0.2.2-py3-none-any.whl').namelist())"
```

The artifacts must not contain `sample/`, `.env`, API keys, or ASS files. They
must contain the project `LICENSE`, `THIRD_PARTY_NOTICES.md`, and the bundled
KyleBing license under `subpeeko/data/`.

## Test the wheel

```bash
python -m pip install --force-reinstall --no-deps dist/subpeeko-0.2.2-py3-none-any.whl
subpeeko --help
```

Use an isolated environment for this check so that the wheel is tested instead
of an editable checkout.

## Manual publish

If you are not using the tagged release workflow, upload the artifacts manually
after reviewing the release notes, license files, and package index settings.

```bash
python -m twine upload dist/*
```

## Automated tagged releases

Pushing a tag such as `v0.2.1` starts `.github/workflows/release.yml`. The
workflow checks that the tag matches `pyproject.toml`, runs the tests, builds
and checks both distributions, publishes them to PyPI, and creates a GitHub
Release with the files attached. The Release description comes from the
matching version section in `RELEASES.md`.

Before the first automated release, add a PyPI Trusted Publisher for:

- owner: `zhaneran`
- repository: `SubPeeko`
- workflow: `.github/workflows/release.yml`
- environment: `pypi`

After that one-time setup, update the version, commit it, and push the matching
`vX.Y.Z` tag. The workflow uses short-lived OIDC credentials; no PyPI API token
is stored in GitHub Secrets.
