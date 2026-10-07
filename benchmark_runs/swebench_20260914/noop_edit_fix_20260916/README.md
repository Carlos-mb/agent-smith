# Refusing a no-op `edit_file` — before and after (16 September 2026)

`scikit-learn__scikit-learn-13439`, `codestral-2508`, `https://api.mistral.ai/v1`.
Both runs were validated with `moulinette_eval validate swebench`, without
`--skip-metrics`. **Both failed.** This directory documents a harness defect that
was fixed, not a task that was rescued.

## The defect

From its fifth step onward the model sent `edit_file` calls whose `old_str` and
`new_str` were identical character for character. The file never changed, and the
tool answered `Edit applied successfully.` every time. The model asked whether its
change had landed, we confirmed a change that had not happened, the tests stayed
red, and it repeated the same call.

Measured over every saved SWE-bench run — 82 `solution.json`, 7 distinct tasks, 66
runs containing edits: **13 no-op calls out of 110**, all 13 in the `before` run,
covering 139,168 input tokens. `_EDIT_PROGRAM` in `agent_smith/swebench_tools.py`
now refuses that case, as a third refusal beside the ambiguous match and the result
that would not compile. The other 97 edits cannot match the condition, so the
change can only act where the tool used to report a success that never occurred.

## The two runs

| | `before/` | `after/` |
| --- | --- | --- |
| Run | full three-task run, 14:27 | direct run with the fix, 15:24 |
| Verdict | `Overall: FAILED` | `Overall: FAILED` |
| Iterations | 30 / 30 | 30 / 30 |
| Input tokens | 288,129 | 270,596 |
| No-op edits | **13** | **0** |
| Container cleanup | OK | OK |

## What the `after` run shows

The no-op loop is gone, and a different one replaced it: the model now alternates
between `return len(self.steps)` and `return len(self.steps_)`, undoing its own
edit nine times — three distinct edits, ten applied. `run_tests` returned
`1 failed, 40 passed` on all ten calls, so nothing ever improved. The remaining
failure is the model's: it does not know how to fix this bug.

Detecting that oscillation is **not** proposed. It is the loop warning of section
5.5 of `BENCHMARK_REPORT.md`, already measured at 1/4 against 1/2 without it, and
discarded.

This task also passed with `codestral-2508` before: see
`../ablation/observation_stop/codestral-2508/scikit-learn-13439/`, `Overall: PASSED`
in 5 iterations and 11,701 input tokens. It is a coin flip, like
`sympy__sympy-14711`.

## Reproducing

```bash
# in moulinette/
uv run --python 3.10 moulinette_eval dump swebench \
  --task-id scikit-learn__scikit-learn-13439 --output task.json
# in student/
uv run --env-file .env --python 3.10 python -m agent_swebench \
  --task-file task.json --output solution.json \
  --model-name codestral-2508 --provider-url https://api.mistral.ai/v1
# in moulinette/
uv run --python 3.10 moulinette_eval validate swebench task.json solution.json
```
