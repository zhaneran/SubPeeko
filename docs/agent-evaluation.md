# Agent Evaluation Notes

This document records engineering guidance for future Agents working on
SubPeeko. It is not a user-facing feature description. Keep subtitle excerpts,
API responses, credentials, and other private data in ignored local files.

## Shipped processing path

The current command-line implementation uses one configured OpenAI-compatible
Chat Completions model. It computes vocabulary hints locally, sends eligible
bilingual dialogues in batches, and asks the model to decide which words,
phrases, grammar points, and context-specific meanings exceed the selected
level. The model also writes the concise Chinese explanations that are inserted
into the generated ASS file.

The default batch size is five target dialogues and the default concurrency is
four requests. Nearby dialogues are included as context in each request. A
separate decision or pre-filter model is not part of the shipped processing
path.

## Evaluation before skipping calls

Do not skip a dialogue because a word-list lookup finds no advanced word. A
phrase, usage, grammatical construction, or word sense can still be advanced.
Before introducing a local pre-filter or a second model that suppresses a
Chat Completions call, evaluate it against all of the following.

1. Human annotations that identify required language points and their levels.
2. The current all-dialogue model path using the same source and prompt.
3. Recall of required annotations, contextual meaning accuracy, false-positive
   rate, and model calls saved.

Use a representative sample of at least 100 to 200 dialogues before changing a
default. A small exploratory run can identify implementation problems, but it
cannot establish that skipping is safe. Keep the source, prompt, model,
threshold, and evaluation date with the local report so another Agent can
reproduce the result without placing private subtitles in Git.

## Reporting rules

User-facing README text should describe implemented commands, options, data
flow, output behavior, and known operational constraints. Historical timings,
small-sample comparisons, tentative model recommendations, and unimplemented
APIs belong in local reports or this document. Update this document when an
experiment changes an engineering decision, then update `AGENTS.md` if a new
constraint should apply to future work.
