# Ablation: a second prompt example showing how to close the cycle

**Result: not adopted.** No evidence of improvement, and a measurable cost when
the run fails.

## What changed

The SWE-bench system prompt already carries one example, which shows how to
*find* code (`search_function_or_class_definition_in_code`). Section 4 of
`BENCHMARK_REPORT.md` says that finding the file is not the bottleneck — every
passing run touches the file it will patch by step 1–3 — and that submission
is: models spend 2 or 3 iterations, up to 60% of the task's input tokens,
re-running tests and printing `git diff` before `final_answer`.

So a second example was added after the first one, showing the *end* of the
cycle. Nothing else was touched.

```
Then change and check in the same step, and wait for the real Observation:
Thought: I will apply the minimal fix and run the tests in one step.
```python
print(edit_file(filepath="/testbed/package/module.py", old_str="    return handler", new_str="    return handler or default_handler"))
print(run_tests())
```
<end_code>
As soon as an Observation shows the tests passing, submit in the next response.
Do not re-run the tests and do not print git diff first: those extra steps are the
most expensive, because each one resends the whole history.
```

Paths in the example are neutral (`/testbed/package/module.py`) on purpose: the
example in another project uses real sympy paths, which risks sending the model
to an invented path on a django or xarray task.

## Method

18 September 2026, `codestral-2508` (Mistral), task `sympy__sympy-14711`, three
runs per condition, alternating base/variant so the hour-to-hour variation
section 3 warns about is shared evenly. Every run validated with
`moulinette_eval validate swebench`, without `--skip-metrics`.

`closing_example/` holds the three runs with the example;
`without_closing_example/` the three without it.

## Results

| Run | Result | Iterations | Input tokens | Output tokens |
| --- | --- | ---: | ---: | ---: |
| without, run1 | FAILED | 28 | 206,938 | 10,000 |
| without, run2 | FAILED | 30 | 162,897 | 10,000 |
| without, run3 | FAILED | 27 | 169,217 | 10,000 |
| with, run1 | **PASSED** | 14 | 51,178 | 942 |
| with, run2 | FAILED | 29 | 288,921 | 2,316 |
| with, run3 | FAILED | 27 | 256,265 | 10,000 |

0/3 without, 1/3 with. That single pass is inside the run-to-run noise section
5.1 already measured. Against it: in the runs that fail, the variant spends
272,593 input tokens on average against 179,684. When it fails, it fails more
expensively — and SWE-bench is graded on efficiency.

## What it does show

The example is obeyed. Counting tool calls across the six runs:

| Run | `edit_file` | `run_tests` |
| --- | ---: | ---: |
| without, run1 | 21 | 3 |
| without, run2 | 0 (29 `read_file`) | 0 |
| without, run3 | 16 | 1 |
| with, run1 | 5 | 5 |
| with, run2 | 14 | 14 |
| with, run3 | 15 | 4 |

Without the example the model edits without testing; with it, editing and
testing go together — run2 has 14 and 14 exactly. The mechanism works. It just
does not break the loop, it **changes what the loop repeats**:

- without/run1 repeated the same `edit_file` **12 times**, each answered
  `edit_file refused: expected exactly one match of old_str, found 0`. Its
  `old_str` was a whole docstring of `_check_vector`.
- without/run2 repeated the same four-line `read_file` **26 times**, never
  editing anything.
- with/run2 repeated `print(run_tests())` **14 times**.

This is the same finding as section 5.5: on this task `codestral-2508` ignores
what it is told and repeats itself.

## What it found on the way

Across the 155 steps of these six runs: **0** invented functions, **0** blocked
imports of the project, and **31 of 47** `edit_file` refusals were `found 0` —
30% of all steps wasted on edits the model reissued unchanged. `edit_file`
already explains *where* the matches are when `old_str` appears more than once;
it says nothing when it appears zero times. Whether filling that gap helps is
**still unmeasured**. A follow-up run the same morning, adding that hint, was
invalidated: an hour later `codestral` behaved completely differently on the
same task — 128 `read_file` calls against 34 `edit_file` over 172 steps, and
only **2** `found 0` refusals against 31 here, so the change was almost never
exercised. Its replies had also shrunk from about 2,100 characters to 215, with
a stray `<!-- omit in toc -->` appended. Section 3's warning, "the same model
varies with the hour", applies to Mistral too; that round was discarded rather
than reported.
