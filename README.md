# SubPeeko

SubPeeko is a planned tool for turning bilingual English–Chinese ASS subtitles
into English-learning subtitles. It will preserve the original English and
show concise Chinese explanations for language points above the learner's
selected level.

## Status

The project is in the research and planning stage. There is no working
application yet.

The intended learning levels are Chinese high school, CET-4, CET-6, and
postgraduate entrance English. Knowledge is cumulative across these levels.
Vocabulary lists can inform classification, while phrases, meanings, and
grammar also need to be considered in context.

The planned approach is to handle reliable cases locally and use a configurable
model API for ambiguous cases and semantic alignment with the original Chinese
subtitles. Its accuracy and cost will be evaluated against an all-model
baseline and human annotations before relying on local filtering.

## Configuration

[.env.example](.env.example) records the planned API settings. When model
integration is implemented, copy it to `.env` and provide the service's base
URL, model name, and API key. `.env` is ignored by Git; never commit real keys.
The settings are placeholders and are not read by an application yet.

## Subtitle samples

The local `sample/` directory is intentionally excluded from Git. Use subtitles
you are allowed to process and keep private media and generated output out of
the repository.

## Vocabulary data

[KyleBing/english-vocabulary](https://github.com/KyleBing/english-vocabulary)
is a candidate research source. Its grade labels and the provenance and
permissions of its underlying data need evaluation before redistribution.
