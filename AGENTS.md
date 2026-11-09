# Agent instructions

- Write project documentation and code comments in English by default.
- Preserve the original English, timings, ASS styling, and unrelated subtitle
  events when processing supported input. Never overwrite the input file.
- Treat the learning levels as cumulative: Chinese high school, CET-4, CET-6,
  then postgraduate entrance English. A vocabulary-list match alone does not
  establish the difficulty of a phrase, usage, or word sense.
- Prefer reliable local processing and use the model for ambiguous language
  points and semantic alignment. Validate accuracy and missed points against
  human annotations and an all-model baseline before skipping model calls.
- Keep `sample/`, `.env`, API keys, and private subtitle contents out of Git.
  Do not print credentials or subtitle contents in routine logs.
- Check the provenance and license of third-party vocabulary data before
  bundling it. Keep changes focused and test behavior that matters.
