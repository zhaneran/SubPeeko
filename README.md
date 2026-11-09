# SubPeeko

SubPeeko creates English-learning subtitles from bilingual English–Chinese ASS
files. It retains the original English and replaces the dialogue's Chinese
translation with concise annotations for language points above the selected
learning level.

This is an initial local release. It has not been published to PyPI.

## Install

With Python 3.10 or later, install from a local checkout:

```bash
python -m pip install .
```

When using a virtual environment, activate it first so that the `subpeeko`
command is available. A future public release is intended to support
`pip install subpeeko`.

## Configure the model

```bash
subpeeko config       # interactively set the API root, model, and API key
subpeeko config show  # show settings without revealing the key
subpeeko config test  # send a small request to verify the connection
```

The API must support OpenAI-compatible Chat Completions. Set the base URL to the
provider's API root, for example `https://example.com/v1`, without appending
`/chat/completions`. The connection test makes a real request and may incur a
charge.

The model name and base URL are stored in the user's configuration directory.
The API key is stored in the system credential store, not that configuration
file. If no supported credential store is available, set `SUBPEEKO_API_KEY` in
the environment. Non-interactive environments can set all three variables:

```text
SUBPEEKO_BASE_URL=https://example.com/v1
SUBPEEKO_MODEL_NAME=your-model
SUBPEEKO_API_KEY=your-api-key
```

Environment variables override the current directory's optional `.env` file,
which in turn overrides saved settings. The key from either source takes
priority over the credential store. See [.env.example](.env.example); never
commit a real `.env` file or put the key on the command line.

## Convert subtitles

```bash
subpeeko "movie.ass" --level cet4
subpeeko "./subtitles" --level cet4
subpeeko "./subtitles" --level cet4 --recursive
```

The available levels are `highschool`, `cet4`, `cet6`, and `postgrad`, in
ascending cumulative order. Each result is written beside its input, for example
`movie.cet4.subpeeko.ass`. The input is never overwritten. Existing results are
not replaced unless `--overwrite` is specified, and generated files are skipped
when scanning a directory. A directory is scanned without recursion by default.

Use `--dry-run` to list inputs and destinations without making model requests or
writing files. In a batch, errors are reported per file and remaining inputs are
still processed; a nonzero exit status indicates a failure.
Model requests contain up to five target dialogues by default; use
`--batch-size` to choose a value from 1 to 100 for a provider that supports
larger or smaller requests. Timed-out or malformed batches are split and
retried automatically.

## How it works and current limits

Each identified bilingual dialogue is sent to the configured model, along with
the original Chinese and nearby dialogue as context. Word-list hints are
computed locally, and dialogues are grouped into batches to reduce the number
of requests. Local rules do not skip dialogue based on its apparent difficulty:
that optimization needs comparison with human annotations and an all-model
baseline first. The model can still miss a language point or misjudge its level
or meaning; review the output before relying on it for learning.

SubPeeko preserves original event timing, English text, styles, metadata, and
other events. It processes confidently identified bilingual dialogue whose
Chinese and English occupy separate contiguous ASS line groups. Single-line
mixed-language or otherwise ambiguous layouts are kept unchanged. The input
encoding is preserved for UTF-8, UTF-16 with a byte-order mark, and GB18030.
If a model response is incomplete or invalid, no result is written for that
file. Review long annotations for readability during short subtitle events.

The local `sample/` directory is excluded from Git and distribution packages.
Use subtitles you are allowed to process; their text is sent to your configured
model provider. Vocabulary data provenance and license information are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The source lists are useful
references but are not official exam syllabuses, and their underlying
redistribution permissions need review before public release.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```
