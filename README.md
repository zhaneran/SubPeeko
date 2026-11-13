# SubPeeko

[中文文档](README.zh-CN.md)

<p>
<a href="https://github.com/zhaneran/SubPeeko/actions/workflows/tests.yml?query=branch%3Amain"><img src="https://github.com/zhaneran/SubPeeko/actions/workflows/tests.yml/badge.svg?branch=main" alt="Build status"></a>
<a href="https://github.com/zhaneran/SubPeeko/releases"><img src="https://img.shields.io/github/v/release/zhaneran/SubPeeko?display_name=tag" alt="Latest release"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/zhaneran/SubPeeko" alt="License"></a>
</p>

SubPeeko turns bilingual English–Chinese ASS subtitles into English-learning
subtitles. It keeps the original English and adds concise Chinese notes for
language points above the selected learning level.

## What it looks like

SubPeeko changes the usual Chinese-over-English layout into an English-first
layout:

| Before (Chinese / English) | After (English / notes) |
| --- | --- |
| 中文翻译<br>*This appears to be a misunderstanding.* | *This appears to be a misunderstanding.*<br>**misunderstanding: 误会； appears: 似乎** |
| 他们暂缓了提案<br>*They tabled the proposal.* | *They tabled the proposal.*<br>**tabled: 暂缓（提案）** |
| 我需要再想想<br>*I need to mull it over.* | *I need to mull it over.*<br>**mull it over: 仔细考虑** |

When the source Chinese font is larger than the English font, the generated
subtitle exchanges those two sizes as well.

## Install

Python 3.10 or later is required.

```bash
python -m pip install subpeeko
```

To install from a checkout instead:

```bash
python -m pip install .
```

## Configure the model

Set the API root, model name, and API key interactively:

```bash
subpeeko config
subpeeko config show
subpeeko config test
```

The endpoint must support OpenAI-compatible Chat Completions. Enter its API
root, such as `https://example.com/v1`; do not append
`/chat/completions`. The connection test sends a real request.

For scripts and CI, set:

```text
SUBPEEKO_BASE_URL=https://example.com/v1
SUBPEEKO_MODEL_NAME=your-model
SUBPEEKO_API_KEY=your-api-key
```

You can also use the optional local `.env` file. Keep real keys out of Git and
do not put them in command-line arguments.

## Convert subtitles

Convert one file:

```bash
subpeeko "movie.ass" --level cet4
```

Convert a directory, or include subdirectories:

```bash
subpeeko "./subtitles" --level cet4
subpeeko "./subtitles" --level cet4 --recursive
```

The levels are cumulative: `highschool`, `cet4`, `cet6`, and `postgrad`.
The result is written beside the input, for example
`movie.cet4.subpeeko.ass`. The input is not overwritten.

Useful options:

| Option | Purpose |
| --- | --- |
| `--recursive` | Include subdirectories when the input is a directory. |
| `--overwrite` | Replace an existing generated file. |
| `--dry-run` | List input and output paths without calling the model or writing files. |
| `--batch-size N` | Set the number of target dialogues per request. |
| `--concurrency N` | Set the number of requests that may run at once. |
| `--no-resume` | Ignore saved progress and start fresh. |
| `--thinking {off,on,auto}` | Choose the model's thinking mode. |

For all available options, run:

```bash
subpeeko --help
```

## Output behavior

- English stays on the top line and generated Chinese notes go below it.
- Original timing, English text, encoding, and unrelated ASS events are kept.
- Ambiguous or unsupported subtitle layouts are left unchanged.
- If a result already exists, SubPeeko stops unless `--overwrite` is used.
- `subpeeko config show` displays the current settings without revealing the API key.

SubPeeko is released under the [MIT License](LICENSE).
