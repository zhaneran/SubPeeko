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

SubPeeko processes up to four batches concurrently by default. The default
per-process budgets are 60 requests per minute and 5,000,000 input and output
tokens per minute. The TPM default matches an Alibaba Cloud `qwen3.8-flash`
quota in Beijing; the RPM default is a conservative client setting, not a
provider limit. Check your provider, model, region, and account quota before
using these defaults, and reserve capacity for any other applications.

The defaults can be changed independently. For example:

```bash
subpeeko "movie.ass" --level cet4 --concurrency 2 --rpm 30 --tpm 500000 --qps 0.5
subpeeko "movie.ass" --level cet4 --concurrency 1  # process batches serially
```

`--qps` is optional and is capped at RPM / 60. The limiter uses 80% of the
configured quotas, spreads requests, and
reserves estimated input plus output tokens for every request, including
retries. `--max-output-tokens` controls the output reservation and API output
limit when rate limiting is enabled (default: 2048). Oversized batches may be
split after a failed response. A 429 response pauses subsequent requests before
one retry, using a numeric `Retry-After` when supplied.

Token reservation uses request UTF-8 bytes plus a fixed allowance rather than
the provider's tokenizer. This is a conservative estimate, not a guarantee:
providers may use different accounting or burst rules, and account quotas may
be shared with other processes. Allocate only this process's available share and
monitor the provider's actual usage.

Alibaba Cloud's `decision-model-preview` uses the separate
[System One API](https://help.aliyun.com/zh/model-studio/decision-model-api)
and does not generate text, so it cannot replace the Chat Completions model
needed to produce Chinese explanations. Its use as a pre-filter requires an
accuracy evaluation before any dialogue can be skipped.

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
model provider.

## Vocabulary source and updates

The bundled word list is derived from
[KyleBing/english-vocabulary](https://github.com/KyleBing/english-vocabulary),
which provides a BSD 3-Clause license. SubPeeko keeps normalized word heads and
their earliest associated level. The exact upstream revision in each package is
recorded in `subpeeko/data/vocabulary-source.json`; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and provenance.
These lists are references, not official exam syllabuses. The underlying data's
redistribution permissions need review before public release.

Each source-distribution or wheel build checks the upstream repository for a
new revision and, when available, builds an updated list into the package. It
checks the upstream license and validates the downloaded lists first. If the
check fails, the build warns and uses the bundled snapshot. The source checkout
is not modified, and installed SubPeeko does not fetch vocabulary at runtime.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```
