# Second MBPP task with Ling — 2026-09-12

Carlos requested one different moulinette exercise after choosing
`inclusionai/ling-3.0-flash-vl:free` with the original prompt on task 396.
Moulinette's random `dump mbpp` selected task **163**, calculating the area of a
regular polygon. This was one new agent run, without model/prompt changes,
manual solution edits or retries of the whole task.

## Result

**Correctness: PASSED / Metrics: VALID / Overall: PASSED.**

| Metric | Task 163 | Limit |
| --- | ---: | ---: |
| Iterations | 2 | 10 |
| HTTP requests | 2, no retries | — |
| Input tokens | 1,505 | 6,000 |
| Output tokens | 169 | 1,500 |
| Total task time | 3.537138379 s | 120 s |

Both API responses reported `inclusionai/ling-3.0-flash-vl:free`. The first
response stored the candidate and called `run_tests`; MCP/Docker returned passing
public tests. The second called `final_answer(solution)` using the persistent
variable. Moulinette then tested the submitted solution and validated its metrics.
Its process exited 0. The agent CLI also exited 0 and wrote `success: true` with
no error. Token totals equal the sums of the recorded steps.

The system prompt is byte-for-byte identical to the successful task 396 result.
The saved configuration is identical to `configs/models_template.json` at the
time of this run. Preparation and cleanup are included in the reported task
time; the separate moulinette validation is not. A subsequent Docker check found
no containers with the project's MBPP session label.

Codex ran the CLI and moulinette with **Python 3.10.12** and uv. The agent's test
container used `python:3.10.12-slim`; moulinette's configured evaluator used
`python:3.11-slim`. These were the same settings as the earlier comparison.
The validator emitted a Requests dependency warning but completed both checks.
No implementation code changed and pytest was not repeated for this
documentation and live-test request.

## Evidence

- [Public task JSON](task.json) and [dump output](dump.log).
- [Configuration snapshot](models_config.json), containing environment variable
  names, without secret values.
- [SolutionOutput](solution.json), including the full system prompt, raw responses,
  executed code, observations and measured usage.
- [DEBUG stderr](stderr.log) with IA, MCP and Docker exchanges; [stdout](stdout.log).
- [Full moulinette validation](validation.log).
- [Prompt, configuration, model, token and credential checks](verification.log).
- [Earlier successful task 396](../mbpp_comparison_20260912/01b_ling_original_prompt/solution.json).

## Commands used

From `moulinette/`, after creating this evidence directory:

```bash
UV_CACHE_DIR=/tmp/agentsmith-uv-cache \
uv run --offline --no-sync --python 3.10 moulinette_eval dump mbpp \
  --output ../student/benchmark_runs/mbpp_second_task_20260912/task.json \
  > ../student/benchmark_runs/mbpp_second_task_20260912/dump.log 2>&1
```

The dump command is random. Reuse the saved `task.json` to repeat task 163.
From `student/`, using the local gitignored `.env`:

```bash
cp configs/models_template.json benchmark_runs/mbpp_second_task_20260912/models_config.json
UV_CACHE_DIR=/tmp/agentsmith-uv-cache \
AGENT_SMITH_LOG_LEVEL=DEBUG \
AGENT_SMITH_MODELS_CONFIG=benchmark_runs/mbpp_second_task_20260912/models_config.json \
uv run --env-file .env --offline --no-sync --python 3.10 python -m agent_mbpp \
  --task-file benchmark_runs/mbpp_second_task_20260912/task.json \
  --output benchmark_runs/mbpp_second_task_20260912/solution.json \
  --model-name inclusionai/ling-3.0-flash-vl:free \
  --provider-url https://openrouter.ai/api/v1 \
  > benchmark_runs/mbpp_second_task_20260912/stdout.log \
  2> benchmark_runs/mbpp_second_task_20260912/stderr.log
```

From `moulinette/`:

```bash
UV_CACHE_DIR=/tmp/agentsmith-uv-cache \
uv run --offline --no-sync --python 3.10 moulinette_eval validate mbpp \
  ../student/benchmark_runs/mbpp_second_task_20260912/task.json \
  ../student/benchmark_runs/mbpp_second_task_20260912/solution.json \
  > ../student/benchmark_runs/mbpp_second_task_20260912/validation.log 2>&1
```

These commands describe the recorded run. Use a new output location when
repeating it to preserve this evidence. Two successful exercises do not establish
a general success rate or an examination pass.
