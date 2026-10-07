# Validated SWE-bench tasks — 14 September 2026

Each directory holds that task's `task.json`, `solution.json` and the moulinette
output. Every run below was validated with `moulinette_eval validate swebench`,
without `--skip-metrics`.

## Tasks run

Six tasks were run: the three the subject suggests for first tests
(`sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629`) and three
more (`sympy__sympy-18189`, `django__django-11066` and
`scikit-learn__scikit-learn-13439`). All six pass here with at least one model:
five with `gemini-3.5-flash-lite`, and `sympy__sympy-14711` with
`dots-studio/dots-3-note-preview:free`. `gemini-3.5-flash-lite` failed that one
every time: twice on its own (below), twice in full three-task runs, once after
the `run_tests` fix (`ablation/run_tests_fix/`) and once with a prompt variant
(`ablation/two_sentences/`).

`codestral-2508`, the SWE-bench model from 15 to 17 September and the first
backup after that, passes all six with
its final configuration. `sympy__sympy-14711` passed in one of its two runs.
Its runs are in `ablation/observation_stop/` (all six tasks; the configuration
without the `Observation:` stop is in `ablation/without_observation_stop/`) and
`run_codestral_20260915/`: a full three-task run, 3/3 on
`sympy__sympy-14711` (15 iterations, 55,614 input tokens), `django__django-11066`
(5, 13,316) and `sympy__sympy-13480` (5, 9,772). That directory keeps each
task's `task.json` and `solution.json`.

**Correction, 16 September:** "passes all six" above describes that campaign, not
a reliable rate. `scikit-learn__scikit-learn-13439` failed twice that day with
`codestral-2508` — in a full three-task run and in a direct re-run — after
passing in both ablation variants. With `sympy__sympy-14711` it is the second
task that goes one in two. Both runs of that day, with their three files each, are
in `noop_edit_fix_20260916/`, which also documents the `edit_file` defect they
exposed.

**Second correction, 18 September:** "one in two" on `sympy__sympy-14711` is now
optimistic. Six more runs of that task with `codestral-2508` that day, three per
condition of the ablation in `ablation/closing_example/` and
`ablation/without_closing_example/`, **all failed**. Its record there is closer
to one in nine. It remains the first SWE-bench backup — it passes the other five
tasks — but the figure to quote is the lower one. Those runs also
showed the model drifting within the hour: replies fell from about 2,100
characters to 215 with a stray `<!-- omit in toc -->` appended, and it moved
from editing compulsively to looping on `read_file`. The README in
`ablation/closing_example/` records both.

`django__django-12308` and `scikit-learn__scikit-learn-11310` were also run, and
failed. They are listed for completeness.

| Task | Model | Iterations | Input tokens | Output tokens | Time | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `django__django-11066` | gemini-3.5-flash-lite | 7 | 26,604 | 413 | 13 s | **PASSED** |
| `sympy__sympy-18189` | gemini-3.5-flash-lite | 7 | 23,054 | 411 | 83 s | **PASSED** |
| `sympy__sympy-13480` | gemini-3.5-flash-lite | 8 | 27,767 | 455 | 24 s | **PASSED** |
| `pydata__xarray-4629` | gemini-3.5-flash-lite | 8 | 32,070 | 280 | 16 s | **PASSED** |
| `scikit-learn__scikit-learn-13439` | gemini-3.5-flash-lite | 14 | 74,031 | 2,359 | 60 s | **PASSED** |
| `sympy__sympy-14711` | dots-3-note-preview:free | 26 | 96,724 | 4,799 | 100 s | **PASSED** (15 Sep) |
| `sympy__sympy-14711` | gemini-3.5-flash-lite | 30 | 263,658 | 4,609 | 52 s | FAILED — iteration limit, no final answer (15 Sep) |
| `sympy__sympy-14711` | gemini-3.5-flash-lite | 30 | 274,622 | 5,057 | 54 s | FAILED — same, second attempt (15 Sep) |
| `django__django-12308` | gemini-3.5-flash-lite | 26 | 201,313 | 974 | 36 s | FAILED — patch submitted but it does not fix the issue |
| `scikit-learn__scikit-learn-11310` | gemini-3.5-flash-lite | 29 | 292,286 | 6,327 | 50 s | FAILED — input budget exhausted before a patch |

`sympy__sympy-23534`, the identifier the subject uses as an example, also passes
with `dots-studio/dots-3-note-preview:free` (16 iterations, 98,430 input tokens,
58 s).

Across the six passing runs: **10.0 iterations on average and 16% of the input
budget**. Limits are 30 iterations, 300,000 input tokens, 10,000 output tokens
and 900 seconds.

Task images were pulled beforehand, so the measured times exclude the download.

## What each failure is

`django__django-12308` is an honest miss: the agent explored, edited and
submitted a diff, and moulinette judged the patch wrong. `scikit-learn-11310`
ran out of input budget at iteration 29 — the history window spends the
remaining allowance evenly across the remaining iterations, so a task needing
all thirty iterations with large observations consumes it exactly.

## Reproducing one

```bash
# in moulinette/
uv run --python 3.10 moulinette_eval dump swebench --task-id sympy__sympy-13480 --output task.json
# in student/
AGENT_SMITH_MODELS_CONFIG=configs/models_template.json \
uv run --env-file .env --offline --no-sync --python 3.10 python -m agent_swebench \
  --task-file task.json --output solution.json \
  --model-name gemini-3.5-flash-lite \
  --provider-url https://generativelanguage.googleapis.com/v1beta/openai
# in moulinette/
uv run --python 3.10 moulinette_eval validate swebench task.json solution.json
```

## What these runs changed in the agent

Every one of these was found by running the agent against a real task, not by
reading code:

- Models abandon the ```python fence once they see a tool result. Three text
  dialects are now converted (`<tool_call>`, `<tool_use>`) and so are the
  provider's own native `tool_calls` — translating those is what turned
  `pydata__xarray-4629` from a first-iteration death into a pass.
- An unusable model response is an observation, not the end of the task. That
  took `django__django-12308` from 2 iterations to 26.
- The Gemini timeout is 120 s: 60 s lost two tasks to `ReadTimeout`.
- A final answer must contain `diff --git`. A model once submitted `get_patch`'s
  own "No changes yet." message and the task was recorded as passed.
- `edit_file` used to answer `Edit applied successfully.` to an edit whose
  `old_str` and `new_str` were identical, confirming a change that never happened.
  In `scikit-learn__scikit-learn-13439` the model sent the same no-op edit 13
  times and spent the whole task on it. It is now refused
  (`noop_edit_fix_20260916/`). The task still fails: the model then alternates
  between two wrong edits instead.
