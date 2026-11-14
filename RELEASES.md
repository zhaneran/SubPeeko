# Releases

## 0.2.2 — 2026-11-14

Status: prepared for publication.

This release fixes generated ASS layout and empty annotation rendering.

### Included

- Swap all available ASS style attributes between the English and Chinese
  lines while preserving each line's original font name.
- Remove empty trailing line breaks when no annotation is generated, improving
  compatibility with subtitle players.
- Preserve all source dialogue events and add regression coverage for full style
  swapping and empty annotations.

### Package files

The build produces the following artifacts in `dist/`.

- `subpeeko-0.2.2-py3-none-any.whl`
- `subpeeko-0.2.2.tar.gz`

### Release checklist

1. Run the test suite and build validation described in [BUILD.md](BUILD.md).
2. Inspect both artifacts with `twine check dist/*`.
3. Confirm that `sample/`, `.env`, API keys, and ASS files are absent from the
   artifacts.
4. Create the Git tag `v0.2.2` after the release commit is approved.
5. Let `.github/workflows/release.yml` publish the tag.

## 0.2.1 — 2026-11-14

Status: prepared for publication.

This release adds a tagged GitHub Actions workflow for repeatable package and
GitHub Release publication.

### Included

- Automated tests, distribution builds, metadata checks, PyPI publication, and
  GitHub Release creation for matching `v*` tags.
- PyPI Trusted Publishing through GitHub OIDC, without a stored API token.
- User-focused README documentation retained alongside the release workflow.

### Package files

The build produces the following artifacts in `dist/`.

- `subpeeko-0.2.1-py3-none-any.whl`
- `subpeeko-0.2.1.tar.gz`

### Release checklist

1. Run the test suite and build validation described in [BUILD.md](BUILD.md).
2. Inspect both artifacts with `twine check dist/*`.
3. Confirm that `sample/`, `.env`, API keys, and ASS files are absent from the
   artifacts.
4. Create the Git tag `v0.2.1` after the release commit is approved.
5. Let `.github/workflows/release.yml` publish the tag.

## 0.2.0 — 2026-11-14

Status: prepared for publication.

This release improves the generated subtitle layout for English learning.

### Included

- English-first rendering for supported bilingual dialogue, with generated
  Chinese notes underneath the original English.
- Local ASS font-size overrides that exchange the Chinese and English sizes
  when the source Chinese font is larger.
- Preservation of original English text, timing, encoding, unrelated events,
  and the surrounding style context.
- README examples showing the input and generated subtitle layout.

### Package files

The build produces the following artifacts in `dist/`.

- `subpeeko-0.2.0-py3-none-any.whl`
- `subpeeko-0.2.0.tar.gz`

### Release checklist

1. Run the test suite and build validation described in [BUILD.md](BUILD.md).
2. Inspect both artifacts with `twine check dist/*`.
3. Confirm that `sample/`, `.env`, API keys, and ASS files are absent from the
   artifacts.
4. Create the Git tag `v0.2.0` after the release commit is approved.
5. Upload the artifacts to the intended package index using its approved
   credentials.

## 0.1.0 — 2026-11-12

Status: prepared for publication.

This is the first SubPeeko release. It provides a cross-platform command-line
tool for creating English-learning subtitles from bilingual English–Chinese ASS
files.

### Included

- Python 3.10 and later support.
- `subpeeko` console command for one ASS file or a directory of ASS files.
- Cumulative `highschool`, `cet4`, `cet6`, and `postgrad` learning levels.
- OpenAI-compatible Chat Completions configuration through `subpeeko config`.
- Default concurrent batch processing with configurable request, token, and QPS
  limits.
- Thinking disabled by default through `enable_thinking: false`, with explicit
  `on` and `auto` modes.
- Per-batch retries and local checkpoints for resuming interrupted work.
- Preservation of source English, timing, styling, encoding, and unrelated ASS
  events.
- Bundled vocabulary data derived from KyleBing/english-vocabulary with its
  separate license and provenance notice.

### Package files

The build produces the following artifacts in `dist/`.

- `subpeeko-0.1.0-py3-none-any.whl`
- `subpeeko-0.1.0.tar.gz`

### Release checklist

1. Run the test suite and build validation described in [BUILD.md](BUILD.md).
2. Inspect both artifacts with `twine check dist/*`.
3. Confirm that `sample/`, `.env`, API keys, and ASS files are absent from the
   artifacts.
4. Create the Git tag `v0.1.0` after the release commit is approved.
5. Upload the artifacts to the intended package index using its approved
   credentials.
