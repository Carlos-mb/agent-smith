# Benchmark report — SWE-bench model comparison

Ten models on the same three SWE-bench tasks, plus six ablations. Every
number below is read from a `solution.json` in `benchmark_runs/`, and every
result was checked with `moulinette_eval validate swebench`, never with
`--skip-metrics`. Failures are reported as they happened.

## 1. Setup

**Agent.** This repository at commit `c5853a8` for sections 2 to 5.2. The
`codestral-2508` runs and sections 5.3 to 5.5 use the later code with the two
fixes of section 7. Section 5.6 was measured on 18 September 2026 at commit
`6f6949b`, after the 17 September simplification. One Thought → Code →
Observation loop, nine MCP tools, the task container held open by the agent's
stdin. Task limits from the subject: 30 iterations, 300,000 input tokens,
10,000 output tokens, 900 seconds. Every model uses the same prompt and `configs/models_template.json`:
at most 600 output tokens per request; Gemini and Mistral 120 s timeout and 4
retries, OpenRouter 60 s and 2 retries. `codestral-2508` stops at `<end_code>`
and `Observation:` (section 5.4).

`qwen/qwen3.8-27b` was measured on 17 September 2026 with the code of that day:
the fixes of section 7, `reasoning_effort: "none"`, the same two stop sequences
as `codestral-2508`, 120 s timeout and 10 retries. Groq's free tier allows 8,000
tokens per minute, so a request is often refused with HTTP 429 before
generating; the client waits as long as the provider's `retry-after` asks
before trying again. Its wall-clock times are mostly that waiting.

**Models and providers.** All free tiers: two API keys each for Google and
OpenRouter at the time of the matrix, one for Mistral, one for Groq.

| Provider | Endpoint | Models |
| --- | --- | --- |
| Groq | `api.groq.com/openai/v1` | `qwen/qwen3.8-27b` |
| Mistral | `api.mistral.ai/v1` | `codestral-2508` |
| Google AI Studio | `generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.8-flash` |
| OpenRouter | `openrouter.ai/api/v1` | (free models no longer available as of 2026-09-29) |

**Tasks.** `sympy__sympy-13480`, `sympy__sympy-18189`, `django__django-11066`.

Why these three:

- Two repositories with different test runners (sympy's `bin/test`, Django's
  `runtests.py`), so one project's quirks do not decide the ranking.
- All three pass with the reference model, so a failure points at the model or
  the provider, not at an impossible task.
- Their images are among the smallest of the tasks we ran, about 4 GB each,
  against 5.3 GB for `scikit-learn__scikit-learn-13439` and 7.6 GB for
  `pydata__xarray-4629`. The disk filled once while images were being pulled.

`sympy__sympy-14711`, one of the tasks the subject suggests for first tests and
the hardest one we measured, was run separately after the matrix.
`gemini-3.5-flash-lite` failed all six of its attempts, each time running out
of iterations or input budget with no final answer: two on their own, two in
full three-task runs, one in section 5.3 and one while testing a prompt
variant. `dots-3-note-preview` passed it in 26 iterations with 96,724 input
tokens. `codestral-2508` passed it once in two runs with its final
configuration: 15 iterations and 55,614 input tokens in a full three-task run,
and 30 iterations with no final answer in section 5.4; it also submitted a
wrong patch in a three-task run on 17 September. `qwen/qwen3.8-27b` passed it
in all five of its attempts: three with one Groq account (11, 10 and 7
iterations; 29,908, 31,466 and 19,644 input tokens) and one in each of the two
three-task runs of section 6. The evidence is in
`benchmark_runs/swebench_20260914/sympy-14711/`,
`…/run_codestral_20260915/sympy-14711/` and
`…/qwen_20260917/one_account/sympy-14711/run1` to `run3`.

**When.** `gemini-3.5-flash-lite` on 14 September 2026; the other seven models
and the ablations on 15 September 2026; `codestral-2508` on the evening of 15
September; `qwen/qwen3.8-27b` on 17 September. One run per model × task.

## 2. Results

Iterations / input tokens / output tokens / wall-clock time. Each cell is backed
by `benchmark_runs/swebench_20260914/<path>/solution.json` next to its
`validation.txt`.

| Model | `sympy__sympy-13480` | `sympy__sympy-18189` | `django__django-11066` |
| --- | --- | --- | --- |
| `qwen3.8-27b` | **PASS** · 7 / 17,619 / 387 / 134 s | **PASS** · 7 / 21,466 / 543 / 164 s | **PASS** · 5 / 15,363 / 216 / 78 s |
| `codestral-2508` | **PASS** · 5 / 9,409 / 200 / 13 s | **PASS** · 4 / 11,234 / 228 / 25 s | **PASS** · 5 / 13,496 / 241 / 13 s |
| `gemini-3.5-flash-lite` | **PASS** · 8 / 27,767 / 455 / 24 s | **PASS** · 7 / 23,054 / 411 / 83 s | **PASS** · 7 / 26,604 / 413 / 13 s |
| `dots-3-note-preview` | **PASS** · 10 / 31,534 / 1,136 / 37 s | **PASS** · 11 / 35,957 / 1,391 / 38 s | **PASS** · 6 / 20,621 / 829 / 25 s |
| `ling-3.0-flash-vl` | **PASS** · 8 / 22,535 / 445 / 20 s | FAIL¹ · 11 / 46,190 / 488 / 41 s | **PASS** · 6 / 22,237 / 351 / 14 s |
| `gemini-3.1-flash-lite` | **PASS** · 17 / 135,665 / 3,265 / 145 s | FAIL² · 22 / 299,603 / 9,999 / 235 s | **PASS** · 15 / 80,720 / 1,199 / 48 s |
| `gemini-3.5-flash` | FAIL³ · 17 / 104,954 / 4,477 / 224 s | FAIL³ · 11 / 64,288 / 1,472 / 82 s | FAIL³ · 1 / 0 / 0 / 4 s |
| `gemini-3.8-flash` | FAIL³ · 1 / 1,703 / 35 / 56 s | FAIL⁴ · 16 / 124,758 / 4,593 / 880 s | FAIL³ · 5 / 12,518 / 1,287 / 242 s |
| `nemotron-3.5-lightning` | FAIL⁵ · 0 / 0 / 0 / 61 s | FAIL⁵ · 11 / 61,147 / 6,600 / 362 s | FAIL¹ · 3 / 8,643 / 1,274 / 26 s |
| `gemma-4-31b-it` | FAIL³ · 1 / 0 / 0 / 3 s | FAIL³ · 1 / 0 / 0 / 2 s | FAIL³ · 1 / 0 / 0 / 2 s |

¹ Submitted a final answer that was not a diff; the agent refuses that as a
success. ² Input budget exhausted. ³ Provider error: HTTP 503 or 429. ⁴ Task
deadline reached. ⁵ A request timed out.

Paths: `qwen3.8-27b` → `qwen_20260917/one_account/<task>/`;
`codestral-2508` → `ablation/observation_stop/codestral-2508/<task>/`;
`gemini-3.5-flash-lite` → `<task>/`; every other model →
`comparison/<model>/<task>/`, where the directory is the model id with `/` and
`:` replaced by `_`. The task directories are `sympy-13480`, `sympy-18189` and
`django-11066`.

Totals over the three tasks:

| Model | Passed | Iterations | Input tokens | Output tokens | Time |
| --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.8-27b` | 3/3 | 19 | 54,448 | 1,146 | 376 s |
| `codestral-2508` | 3/3 | 14 | 34,139 | 669 | 51 s |
| `gemini-3.5-flash-lite` | 3/3 | 22 | 77,425 | 1,279 | 120 s |
| `dots-3-note-preview` | 3/3 | 27 | 88,112 | 3,356 | 100 s |
| `ling-3.0-flash-vl` | 2/3 | 25 | 90,962 | 1,284 | 75 s |
| `gemini-3.1-flash-lite` | 2/3 | 54 | 515,988 | 14,463 | 428 s |
| `gemini-3.5-flash` | 0/3 | 29 | 169,242 | 5,949 | 310 s |
| `gemini-3.8-flash` | 0/3 | 22 | 138,979 | 5,915 | 1,178 s |
| `nemotron-3.5-lightning` | 0/3 | 14 | 69,790 | 7,874 | 449 s |
| `gemma-4-31b-it` | 0/3 | 3 | 0 | 0 | 7 s |

## 3. Provider reliability

Read from the per-step fields `request_time_ms` and `retries`.

- **Average time per step** includes that step's retries.
- **Availability** is usable responses (steps with text) divided by all
  attempts (steps plus retries).
- **Runs ended by the provider** counts HTTP errors and request timeouts.

| Model | Steps | Retries | Steps with no usable text | Availability | Avg time per step | Runs ended by the provider |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `qwen3.8-27b` | 19 | 15 | 0 | 55.9% | 0.5 s† | 0/3 |
| `codestral-2508` | 14 | 0 | 0 | 100% | 1.1 s | 0/3 |
| `gemini-3.5-flash-lite` | 22 | 1 | 0 | 95.7% | 4.3 s | 0/3 |
| `dots-3-note-preview` | 27 | 0 | 0 | 100% | 2.8 s | 0/3 |
| `ling-3.0-flash-vl` | 25 | 3 | 0 | 89.3% | 1.5 s | 0/3 |
| `gemini-3.1-flash-lite` | 54 | 117 | 29 | 14.6% | 6.7 s | 0/3 |
| `gemini-3.5-flash` | 29 | 34 | 3 | 41.3% | 8.7 s | 3/3 (one 503, two 429) |
| `gemini-3.8-flash` | 22 | 24 | 2 | 43.5% | 50.1 s | 2/3 (503) |
| `nemotron-3.5-lightning` | 14 | 0 | 0 | 100%* | 23.1 s | 2/3 (timeout) |
| `gemma-4-31b-it` | 3 | 6 | 3 | 0% | 0.3 s | 3/3 (429) |

\* Overstated. A request that times out ends the run before it is recorded as a
step, so nemotron's two timeouts are missing from both columns.

† Request time only. The 15 retries are HTTP 429 refusals from Groq's 8,000
tokens-per-minute limit, and the waits the provider asked for before each retry
are not in `request_time_ms`; they are why its three runs took 376 s.

What stands out:

- **`qwen3.8-27b` is limited by its free tier, not by the model.** Every
  retry is a 429 refused before generating, so it costs no tokens, only time.
  None of its runs ended because of the provider: waiting as long as
  `retry-after` asks lets the next attempt through.
- **`gemini-3.1-flash-lite` answers with empty text more often than not.** 29
  of its 54 steps had no usable text even after four retries; in
  `sympy-13480`, ten steps in a row. The retries also count against the input
  budget, which is how `sympy-18189` used all 300,000 input tokens in 22
  iterations.
- **`gemini-3.8-flash` is too slow for the time limit.** It averages 50 s per
  step, and 30 iterations at that pace take 1,500 s against a 900 s limit. It
  hit the deadline on `sympy-18189` after 16 iterations.
- **`gemma-4-31b-it` was rate-limited upstream all day.** Every request got a
  429 before generating anything. That is a provider result, not a model
  result.
- **The same model varies with the hour.** `gemini-3.5-flash-lite` averaged
  10.7 s per step on `sympy-18189` on 14 September. In the six ablation runs on
  15 September it made 54 steps with no retries at all. On the afternoon of 14
  September, Google's endpoint returned 503s almost continuously; the runs from
  that afternoon were discarded and repeated for this report.

## 4. Intermediary metrics

Measured on every passing run: the thirteen in section 2 and the six in
section 5.1.

**a) First step that reads or edits a file of the final patch** (exploration
efficiency). The first `read_file` or `edit_file` whose `sandbox_input` names a
file that appears in the submitted diff.

| Model | 13480 | 18189 | 11066 |
| --- | ---: | ---: | ---: |
| `qwen3.8-27b` | 2 | 2 | 2 |
| `codestral-2508` | 2 | 1 | 2 |
| `gemini-3.5-flash-lite` | 2 | 1 | 2 |
| `dots-3-note-preview` | 2 | 3 | 2 |
| `ling-3.0-flash-vl` | 2 | — | 2 |
| `gemini-3.1-flash-lite` | 2 | — | 2 |
| ablation runs (6) | 2, 2 | 2, 2 | 2, 3 |

**b) Iterations between "tests first pass" and `final_answer`** (submission
discipline; 1 is the minimum, because the prompt asks for `final_answer` in a
new response after the model has seen the test result). "Tests first pass" is the first step after the last
edit that either calls `run_tests` or runs a test command through `run_command`
whose output shows a passing summary (sympy `tests finished: … passed` with no
failures, a unittest `OK` line). A `run_tests` call on the final code counts as
passing because it runs the same `eval_script` moulinette runs, and these tasks
passed moulinette. In these runs its own output could not confirm this
(section 7).

| Run | Iterations after tests pass | Input tokens spent after tests pass |
| --- | ---: | ---: |
| `qwen3.8-27b` · 13480 | 1 | 3,994 of 17,619 (23%) |
| `qwen3.8-27b` · 18189 | 1 | 4,059 of 21,466 (19%) |
| `qwen3.8-27b` · 11066 | 1 | 4,162 of 15,363 (27%) |
| `codestral-2508` · 13480 | 1 | 2,713 of 9,409 (29%) |
| `codestral-2508` · 18189 | 1 | 3,396 of 11,234 (30%) |
| `codestral-2508` · 11066 | 1 | 3,576 of 13,496 (26%) |
| `gemini-3.5-flash-lite` · 13480 | 3 | 16,628 of 27,767 (60%) |
| `gemini-3.5-flash-lite` · 18189 | 2 | 7,489 of 23,054 (32%) |
| `gemini-3.5-flash-lite` · 11066 | 2 | 8,487 of 26,604 (32%) |
| `dots-3-note-preview` · 13480 | 3 | 14,829 of 31,534 (47%) |
| `dots-3-note-preview` · 18189 | 1 | 4,098 of 35,957 (11%) |
| `dots-3-note-preview` · 11066 | 1 | 5,085 of 20,621 (25%) |
| `ling-3.0-flash-vl` · 13480 | 2 | 9,085 of 22,535 (40%) |
| `ling-3.0-flash-vl` · 11066 | 1 | 5,398 of 22,237 (24%) |
| `gemini-3.1-flash-lite` · 11066 | 2 | 10,134 of 80,720 (13%) |
| `gemini-3.1-flash-lite` · 13480 | — | never tested the final code |
| ablation, without warning (3 runs) | 1, 2, 2 | 33%, 25%, 20% |
| ablation, with warning (3 runs) | 2, 2, 2 | 50%, 22%, 29% |

Ablation rows are in task order 13480 / 18189 / 11066. Without the warning:
3,739 of 11,435, 9,144 of 37,188 and 9,641 of 48,997. With it: 8,533 of 17,136,
9,842 of 45,236 and 9,179 of 31,246.

**What the metrics say.**

- **Finding the file is not the bottleneck.** Every passing run touches the
  file it will patch by step 1–3, 2 in most cases. Differences in iteration
  counts come from what happens *after* the edit.
- **Submission is, and it depends on the model.** `codestral-2508` submits in
  the step right after its tests pass in all three runs, the minimum. The
  other models do so in only 4 of their 15 measured runs. The rest spend 2 or
  3 iterations, up to 60% of the task's input tokens, re-running tests,
  printing `git diff` and calling `get_patch` before `final_answer`. Those
  late steps are the most expensive ones, because each resends the whole
  grown history.
- **Most models verify through `run_command`, not `run_tests`.** In 5 of the
  10 passing runs of the first eight models, the model never called
  `run_tests` after its last edit and ran the test file itself instead. We
  suspected `run_tests`' output, which hid the result (section 7). Fixing it
  changed nothing: `gemini-3.5-flash-lite` then did not call `run_tests` once
  in four runs (section 5.3). `codestral-2508` is the exception: it calls
  `run_tests` right after its edit in every passing run, and that is where
  its short runs come from.

## 5. Ablation

### 5.1 SWE-bench: the prompt's "the sandbox cannot import the project" warning

**Change.** The system prompt (`agent_smith/swebench_agent.py`,
`build_swebench_system_prompt`) carries three lines telling the model that an
`import` of anything under `/testbed` fails inside the sandbox and that it must
use `run_command` instead. They were added after a model spent 4 of 12
iterations attempting `import sympy`. For the ablation, those three lines were
removed in a temporary copy of the agent. Everything else was identical: same
commit, model (`gemini-3.5-flash-lite`), tasks, limits and day. Each run's
`solution.json` stores its `system_prompt`, which confirms which version ran.

| Task | Without the warning | With the warning (current agent) |
| --- | --- | --- |
| `sympy__sympy-13480` | **PASS** · 5 / 11,435 / 148 / 13 s | **PASS** · 6 / 17,136 / 329 / 15 s |
| `sympy__sympy-18189` | **PASS** · 10 / 37,188 / 869 / 19 s | **PASS** · 11 / 45,236 / 985 / 141 s |
| `django__django-11066` | **PASS** · 13 / 48,997 / 592 / 16 s | **PASS** · 9 / 31,246 / 261 / 12 s |
| **Total** | 3/3 · 28 / 97,620 / 1,609 / 48 s | 3/3 · 26 / 93,618 / 1,575 / 168 s |
| Attempts to import the project | 0 | 0 |

Evidence: `benchmark_runs/swebench_20260914/ablation/without_import_warning/`
and `…/ablation/with_import_warning/`, then `gemini-3.5-flash-lite/<task>/`.

The 141 s on `sympy-18189` is not the model. Step 8 ran
`python setup.py test`, which ran until `run_command`'s 120 s limit; the eleven
model requests took 12 s in total.

**What was learned.**

- **For this model the warning does nothing measurable.** Without it,
  `gemini-3.5-flash-lite` still never tried to import the project, and the
  totals differ by 2 iterations and 4% of input tokens, in opposite directions
  on different tasks.
- **Run-to-run noise is as large as the difference.** The 14 September runs
  used the same agent and model and took 8 / 7 / 7 iterations; the "with
  warning" runs took 6 / 11 / 9. With one sample per cell, a change smaller
  than about four iterations per task cannot be told apart from chance.
- **The warning does not stop the models that do import.** In the matrix,
  `gemini-3.8-flash` tried to import the project 4 times on `sympy-18189`, and
  `gemini-3.1-flash-lite` once on `sympy-13480` (the sandbox refused:
  `ImportError: Import not allowed: sympy`). Both had the warning in their
  prompt.
- **Decision: keep it.** It is three lines, costs nothing measurable, and was
  added for a failure observed with another model, which this data cannot rule
  out.

### 5.2 MBPP: original versus simplified prompt (12 September)

An earlier ablation of the same kind on MBPP task 396, with
`inclusionai/ling-3.0-flash-vl:free`. The simplified prompt (226 words against
294) keeps the same tools, the raw-string solution and the test-then-submit
loop. It drops the 20-word limit on the Thought, the rule against explanatory
comments, the note about preserving backslashes, and "do not also define the
function in the worker".

| Prompt | Result | Iterations | Input / output tokens | Time |
| --- | --- | ---: | --- | ---: |
| Original | **PASS** | 4 | 3,237 / 388 | 7.4 s |
| Simplified | FAIL: the candidate required every character to match | 3 | 2,140 / 262 | 5.6 s |

Evidence: `benchmark_runs/mbpp_comparison_20260912/01b_ling_original_prompt/`
and `04_ling_simple_prompt/`, with both prompts saved next to them. The shorter
prompt saved tokens and lost correctness. The original prompt stayed. This is
a single task and sample, so it shows a direction, not a rate.

### 5.3 SWE-bench: showing the test result in `run_tests` (a tool change)

**Change.** `run_tests` used to return the first and last 2,000 characters of
the eval script's output. Those were git noise and deprecation warnings; the
test summary fell in between (section 7). Now it merges `stderr` into `stdout`
and returns only the section between the script's `>>>>> Start Test Output`
and `>>>>> End Test Output` markers. The code is `run_tests` in
`agent_smith/swebench_tools.py`. Same model and tasks, same day; "before" is
section 5.1's "with the warning" runs, which had identical code apart from this
change.

| Task | Before | After |
| --- | --- | --- |
| `sympy__sympy-13480` | **PASS** · 6 / 17,136 / 329 / 15 s | **PASS** · 7 / 18,749 / 481 / 11 s |
| `sympy__sympy-18189` | **PASS** · 11 / 45,236 / 985 / 141 s | **PASS** · 8 / 28,018 / 637 / 18 s |
| `django__django-11066` | **PASS** · 9 / 31,246 / 261 / 12 s | **PASS** · 7 / 24,575 / 527 / 11 s |
| **Total** | 3/3 · 26 / 93,618 / 1,575 / 168 s | 3/3 · 22 / 71,342 / 1,645 / 40 s |
| Iterations after tests pass | 2, 2, 2 | 2, 2, 2 |
| Calls to `run_tests` | 1 | 0 |
| `sympy__sympy-14711` | FAIL in every earlier attempt | FAIL · 30 / 246,391 / 4,514 / 48 s |

Evidence: `benchmark_runs/swebench_20260914/ablation/run_tests_fix/gemini-3.5-flash-lite/<task>/`.

**What was learned.**

- **The fix is correct but did not change the agent's behaviour.** A unit test
  fails on the old code and passes on the new. But this model almost never
  calls `run_tests`: once in the three runs before, and not at all in the four
  after. It tests with its own `run_command` instead.
- **The 24% fewer input tokens is not an effect.** It is within the
  run-to-run noise measured in 5.1, and the mechanism was never exercised.
- **This refutes the hypothesis behind the change.** The two post-pass
  iterations per task did not move, so hiding the test result was not their
  cause. The fix does not rescue `sympy__sympy-14711` either.
- **Decision: keep it.** The tool is now correct for any model that does use
  it, and the change is a few lines. A change aimed at the real post-pass cost
  would be a prompt rule to submit as soon as the tests pass. That remains
  untested.

### 5.4 SWE-bench: stopping `codestral-2508` at `Observation:` (a configuration change)

**Change.** On its first runs `codestral-2508` had the same stop sequence as
the other models, `<end_code>`, which it never writes. After its code block it
kept going: it wrote an `Observation:` with file contents it had not read, then
another block, until the 600-token cap per request. The only change is adding
`"Observation:"` to its `stop_sequences` in `configs/models_template.json`, so
the provider ends the reply where the real observation should begin. The idea
came from another student's project, whose default stop list is exactly these
two strings. Same code, model, tasks and day, on six tasks.

| Task | Without the stop | With the stop |
| --- | --- | --- |
| `pydata__xarray-4629` | FAIL⁶ · 20 / 164,963 / 10,000 / 105 s | **PASS** · 5 / 14,701 / 387 / 11 s |
| `scikit-learn__scikit-learn-13439` | **PASS** · 11 / 50,613 / 3,333 / 44 s | **PASS** · 5 / 11,701 / 208 / 8 s |
| `sympy__sympy-13480` | **PASS** · 5 / 11,453 / 214 / 11 s | **PASS** · 5 / 9,409 / 200 / 13 s |
| `sympy__sympy-18189` | **PASS** · 4 / 11,055 / 222 / 26 s | **PASS** · 4 / 11,234 / 228 / 25 s |
| `django__django-11066` | **PASS** · 5 / 13,489 / 238 / 10 s | **PASS** · 5 / 13,496 / 241 / 13 s |
| `sympy__sympy-14711` | FAIL⁷ · 16 / 62,376 / 1,968 / 27 s | FAIL⁸ · 30 / 252,497 / 2,849 / 80 s |
| **Total** | 4/6 · 61 / 313,949 / 15,975 / 223 s | 5/6 · 54 / 313,038 / 4,113 / 150 s |
| Replies with an invented `Observation:` | 27 (17 of them in xarray) | 0 |
| Replies cut at the 600-token cap | 21 | 0 |

⁶ Output budget exhausted after 20 iterations spent reading, with no edit.
⁷ Submitted a patch to `_check_vector` although `run_tests` had twice reported
`0 passed, 4 exceptions`; moulinette: correctness FAILED. ⁸ Iteration limit,
with 13 `run_tests` calls and no working fix.

Evidence: `benchmark_runs/swebench_20260914/ablation/without_observation_stop/`
and `…/ablation/observation_stop/`, then `codestral-2508/<task>/`.

**What was learned.**

- **The effect is large and its mechanism is visible.** Invented observations
  went from 27 replies to 0, output tokens fell by 74%, and `xarray-4629` went
  from an exhausted output budget to a pass in 5 iterations. Unlike 5.1 and
  5.3, this is far outside the run-to-run noise.
- **Where the mechanism never fired, nothing moved.** On `13480`, `18189` and
  `11066` the model invented nothing before the change, and the numbers stayed
  within a few hundred tokens. That is what a change acting only through that
  mechanism should produce.
- **It does not solve `sympy__sympy-14711` reliably.** With the stop, the model
  failed it here and passed it in a full three-task run the same
  evening (15 iterations): one of two.
- **Decision: keep it, for this model only.** The other models write
  `<end_code>` and keep their single stop sequence; adding `Observation:` to
  them is untested.

### 5.5 SWE-bench: warning the model when it repeats itself (a loop change, discarded)

**Change.** In the failed `sympy__sympy-14711` run of section 5.4,
`codestral-2508` edited the wrong file, `sympy/vector/vector.py`, and then sent
the same edit and `run_tests` 13 times in turn. Every `run_tests` traceback
named the right file, `sympy/physics/vector/vector.py`. The model had the
information and did not use it, so a new MCP tool would not help. The change
tested was a few lines in the loop: when a block repeated both the code and
the result of an earlier step, the observation added *"Note: you already ran
exactly this code and got exactly this result. Repeating it will not change
anything: re-read the last error or test output and try something
different."* Requiring the same result as well keeps a legitimate repeat, such
as `run_tests()` after a different edit, from triggering it. Replayed over the
65 saved result files, the rule would have fired in 6. Same model,
configuration and task, four runs on the evening of 15 September.

| Run | Result · iterations / input / output / time | Warnings | What happened |
| --- | --- | ---: | --- |
| 1 | FAIL · 30 / 106,702 / 1,714 / 39 s | 25 | The same `read_file` 24 times in a row |
| 2 | FAIL · 30 / 106,239 / 1,719 / 36 s | 24 | The same pattern as run 1 |
| 3 | **PASS** · 11 / 27,423 / 604 / 24 s | 0 | No loop |
| 4 | FAIL⁹ · 23 / 148,344 / 10,000 / 135 s | 0 | Read the wrong file in 10-line slices, 100 lines apart |
| **Total** | 1/4 | | Without the warning: 1/2 (section 5.4 and the three-task run) |

⁹ Output budget exhausted: every reply from step 7 to 22 hit the 600-token cap,
because the model wrote several `Thought:` blocks in a row, and the
`Observation:` stop never fired since it never wrote that word.

Evidence: `benchmark_runs/swebench_20260914/ablation/loop_warning/codestral-2508/sympy-14711/run1/`
to `run4/`.

**What was learned.**

- **The model ignores the warning.** In run 1 the note first appears in the
  observation of step 6, and the model repeats the same call until step 30.
  The note sits in the latest observation, the part the history window always
  sends, so trimming did not hide it.
- **Loops are this model's main failure on this task.** All three failures
  here, and the one in section 5.4, are loops. Run 4's loop reads a
  new range every time, so a rule based on repeated code cannot see it.
- **Decision: discarded.** 1/4 against 1/2 is no improvement, and with four
  runs the difference is within the noise. The change was reverted; the code
  in this repository does not contain it.

### 5.6 SWE-bench: a second prompt example showing how to close the cycle (discarded)

**Change.** The system prompt carries one example, and it shows how to *find*
code (`search_function_or_class_definition_in_code`). Section 4 says that is
not where runs are lost: every passing run touches the file it will patch by
step 1–3, while models spend 2 or 3 iterations and up to 60% of the input
budget after their tests pass, re-running tests and printing `git diff` before
`final_answer`. So a second example was added after the first, showing the
*end* of the cycle: one block that calls `edit_file` and `run_tests` together,
followed by "As soon as an Observation shows the tests passing, submit in the
next response. Do not re-run the tests and do not print git diff first: those
extra steps are the most expensive, because each one resends the whole
history." Its paths are neutral (`/testbed/package/module.py`), unlike the
reference project's, which names real sympy files and could send the model to
an invented path on a django or xarray task. Nothing else changed. Same model,
configuration and task, three runs per condition on 18 September, alternating
between conditions so the hour-to-hour variation of section 3 is shared evenly.

| Run | Without the example | With the example |
| --- | --- | --- |
| 1 | FAIL · 28 / 206,938 / 10,000 | **PASS** · 14 / 51,178 / 942 |
| 2 | FAIL · 30 / 162,897 / 10,000 | FAIL · 29 / 288,921 / 2,316 |
| 3 | FAIL · 27 / 169,217 / 10,000 | FAIL · 27 / 256,265 / 10,000 |
| **Total** | 0/3 | 1/3 |
| Average input tokens of the failing runs | 179,684 | 272,593 |

Tool calls over the same six runs:

| Run | `edit_file` without / with | `run_tests` without / with |
| --- | --- | --- |
| 1 | 21 / 5 | 3 / 5 |
| 2 | 0 / 14 | 0 / 14 |
| 3 | 16 / 15 | 1 / 4 |

Run 2 without the example never edited anything: it spent 29 of its 30 steps
on `read_file`.

Evidence: `benchmark_runs/swebench_20260914/ablation/without_closing_example/`
and `…/ablation/closing_example/`, then `codestral-2508/sympy-14711/run1/` to
`run3/`, with a README recording the exact text that was added.

**What was learned.**

- **The example is obeyed, and that is measurable.** Without it the model edits
  without testing; with it the two go together, exactly 14 and 14 in run 2.
  The mechanism works as intended.
- **It changes what the loop repeats, not whether it repeats.** Without the
  example, run 1 sent the same `edit_file` 12 times, each answered `found 0`,
  and run 2 sent the same four-line `read_file` 26 times. With it, run 2 sent
  `print(run_tests())` 14 times. This is section 5.5's finding again: on this
  task the model repeats itself whatever it is told.
- **One pass out of three is not a result.** Section 5.1 measured the noise;
  this sits inside it. And the failing runs with the example cost 272,593
  input tokens on average against 179,684 — when it fails, it fails more
  expensively, on a benchmark graded by efficiency.
- **Decision: discarded.** The change was reverted; the code in this repository
  does not contain it.

**What it found on the way.** Across the 155 steps, the model never called an
invented function and never tried to import the project from the sandbox.
What it did do was waste 47 steps on refused edits, **31 of them `found 0`** —
30% of every step taken. `edit_file` already reports *where* the matches are
when `old_str` appears more than once (that hint was added after a model
retried blindly for eight iterations); it says nothing when it appears zero
times. Whether closing that gap helps is **unmeasured**: a follow-up run the
same morning was invalidated because `codestral-2508` drifted within the hour —
172 steps with 128 `read_file` against 34 `edit_file`, only 2 `found 0`
refusals against 31 here, and replies down from about 2,100 characters to 215
with a stray `<!-- omit in toc -->` appended. Section 3's "the same model
varies with the hour" applies to Mistral too, and that round was discarded
rather than reported.

## 6. Conclusions

**Selected: `qwen/qwen3.8-27b` (Groq).** It is the only model that solves
`sympy__sympy-14711` reliably: five passes in five attempts, against roughly
one in nine for `codestral-2508` (see the update below), on the hardest task
we measured. With one Groq account it passed all six tasks measured: 3/3 on the matrix
(19 iterations, 54,448 input tokens), `xarray-4629` in 6 iterations,
`scikit-learn-13439` in 8, and `sympy-14711` three times. It submits in the step
right after its tests pass. In full three-task runs it scored 2/3 with
two Groq accounts, losing `scikit-learn-13439` to 429 retries when the client
still waited at most 5 s between keys, and 3/3 with three accounts once the
client waited as long as `retry-after` asked (`14711`, `xarray-4629`, `18189`;
11, 7 and 7 iterations; 93, 62 and 64 s). Its costs: about 60% more input
tokens than `codestral-2508` on the matrix, several minutes per task on one
account, and a free tier of 8,000 tokens per minute and 200,000 per day per
account. Groq also refuses any request above 7,000 input tokens with HTTP 413,
which no wait fixes; this cost `14711` on 29 September, so its configuration
caps the history sent per request (`max_input_per_request: 6000`). Evidence: `qwen_20260917/`.

**First backup: `codestral-2508` (Mistral).** 3/3 on the matrix tasks with 14
iterations and 34,139 input tokens, the fewest of all, less than half of
`gemini-3.5-flash-lite`'s 77,425. It also passed `xarray-4629` and `scikit-learn-13439` in 5 iterations
each, and scored 3/3 in a full three-task run, including
`sympy__sympy-14711` (evidence: `run_codestral_20260915/`). It submits in the
step right after its tests pass, and it needed no retry: its free tier allowed
125 requests and 625,000 tokens per minute. It depends on section 5.4's stop
sequence; without it, it scored 4/6.

**Update, 18 September.** Its record on `sympy__sympy-14711` is worse than the
"one in two" reported earlier: the six runs of section 5.6 all failed, which
puts it near one in nine. It stays the first backup — the other five tasks
measured are solid and it is the cheapest model measured — but its weakness is that one
task, so a run that includes it is likely a 2/3. Those runs also caught it
drifting within a single hour (section 5.6), which is a second reason to check
it on the day rather than trust a stored figure.

**Second backup: `gemini-3.5-flash-lite`.** It passed all nine of its runs on
the matrix tasks, three on 14 September plus six in the ablation, with one
retry in 76 steps, and 2/3 twice in full three-task runs. It used the
fewest input tokens of the first eight models (77,425), and it sits on a
different provider. It has never passed `sympy__sympy-14711`: in the two
attempts examined step by step, its fix reached the sandbox as a function
definition instead of an edit, reached `edit_file` only at step 25 or 28, and
broke the tests. A later replay (29 September) showed that this was partly our
extractor, not the model: in 4 of those 7 definitions the reply also held the
real `edit_file` call in a later block, and we executed the example instead.
In a three-task run on 15 September, the edit it wrote at step 27 was a valid fix
(moulinette: PASSED). Fixed on 1 October: the extractor now runs the first
block that calls a tool.

**Third backup: `dots-studio/dots-3-note-preview:free`.** 3/3, with 100%
availability and no retries. It uses about 14% more input tokens and 2.6× the
output tokens of `gemini-3.5-flash-lite`, on a third provider with a separate
quota. It passed `sympy__sympy-14711` once.

**Also usable: `inclusionai/ling-3.0-flash-vl:free`.** It is the fastest per
step (1.5 s), cheap, and passed 2/3. Its failure was a submission without a
diff, which the agent records as a failure rather than a false pass.

**Discarded, based on this data:**

- `gemini-3.1-flash-lite`: it passes 2/3, but with 6.7× the input tokens of
  `gemini-3.5-flash-lite` (515,988 against 77,425), because more than half its steps
  come back empty. It exhausted the input budget on `sympy-18189`.
- `gemini-3.5-flash` and `gemini-3.8-flash`: 0/3, with availability of 41% and
  44% on the free tier. `gemini-3.8-flash` also cannot fit 30 iterations into
  900 s at 50 s per step.
- `nvidia/nemotron-3.5-lightning:free`: 0/3. It is slow (23 s per step), two
  requests timed out, and it once submitted without a diff.
- `google/gemma-4-31b-it:free`: no usable response at all; the free route was
  rate-limited upstream.

**Limits of these conclusions.** There is one run per cell on free tiers whose
availability changes by the hour. The rows for `gemini-3.5-flash`,
`gemini-3.8-flash` and `gemma-4-31b-it` measure the providers that day at
least as much as the models. Section 5.1 shows the same configuration varying
by up to four iterations per task. `codestral-2508` has one run per task with
its final configuration, plus the three of a full three-task run, all on one evening.
`qwen3.8-27b` was measured on one day, and free tiers change: Groq no longer
offered `llama-3.3-70b-versatile` on 17 September. Both should be measured
again before the evaluation.

**Cost.** Every run used free tiers and cost nothing. The token columns are
what a paid tier would bill.

## 7. Agent defects found while measuring (both fixed)

- **`run_tests` hides the test result from the model.** Its output is capped at
  4,000 characters, keeping the beginning and the end. Here, the beginning is
  the `git status` and mode-change noise the `eval_script` prints, and the end
  is deprecation warnings. The test summary falls in the omitted middle, and
  the reported `exit_code` belongs to the script's last command, not to the
  tests. Fixed on 15 September; section 5.3 measures the effect.
  `test_run_tests_returns_only_the_test_output_section` fails on the old code.
- **A provider timeout ends the task with the bare message `TimeoutError:`.**
  On Python 3.10, the `asyncio.TimeoutError` raised by `asyncio.wait_for` is
  not a subclass of the built-in `TimeoutError` the client catches. The result
  file is still written and the run ends as designed, since a timed-out
  request has unknown usage and is not retried. Only the explanatory message
  and the step record are lost. Fixed: the client also catches
  `asyncio.TimeoutError`, and `test_a_request_timeout_ends_with_an_explicit_message`
  fails on the old code.

The runs in sections 2 to 5.2 were made before both fixes; the
`codestral-2508` runs and sections 5.3 to 5.5, after.

## 8. Reproducing a cell

```bash
# in student/
AGENT_SMITH_MODELS_CONFIG=configs/models_template.json \
uv run --env-file .env python -m agent_swebench \
  --task-file benchmark_runs/swebench_20260914/sympy-13480/task.json \
  --output solution.json \
  --model-name gemini-3.5-flash-lite \
  --provider-url https://generativelanguage.googleapis.com/v1beta/openai
# in moulinette/
uv run moulinette_eval validate swebench \
  ../student/benchmark_runs/swebench_20260914/sympy-13480/task.json \
  ../student/solution.json
```

OpenRouter models use `--provider-url https://openrouter.ai/api/v1`;
`codestral-2508` uses `--provider-url https://api.mistral.ai/v1` and reads
`MISTRAL_API_KEY`; `qwen/qwen3.8-27b` uses `--provider-url
https://api.groq.com/openai/v1` and reads `GROQ_API_KEY`. The task
images were pulled beforehand, so the measured times exclude the download.

## 9. Verification run — 22 September 2026

`qwen/qwen3.8-27b` was measured again, and `gemma-4-31b-it` re-tested, to check
the earlier findings.

**Setup.** Same agent code, limits and configuration; three Groq keys and three
OpenRouter keys. Model selected explicitly with `--model-name` and
`--provider-url`.

**Results.**

| Benchmark | Result | Model | Time |
| --- | --- | --- | --- |
| MBPP | **PASS 5/5** | `qwen/qwen3.8-27b` | 3–4 s per task |
| SWE-bench | **PASS 3/3** | `qwen/qwen3.8-27b` | 83 s (scikit-learn), others faster |

**Qwen remains reliable.** All five MBPP tasks passed at the first attempt, and
all three SWE-bench tasks passed (`scikit-learn__scikit-learn-13439`,
`sympy__sympy-13480`, `django__django-11066`).

**`gemma-4-31b-it` remains unusable on the free tier.** All three OpenRouter
keys returned HTTP 429 before generating, on the first request and on every
retry. This is a provider quota, not a model result: OpenRouter's free tier
allowed about 50 requests per day per account, and the keys had been used up by
earlier runs. A daily quota cannot be waited out within a task, so no client
change can fix it.

**Conclusion.** Qwen remains the recommended model. `gemma-4-31b-it` may be
configured correctly, but OpenRouter's free quota is too small for repeated
runs, and that limit should not be attributed to the model. On 29 September
2026 OpenRouter stopped offering these models for free altogether.
