# Releases

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
