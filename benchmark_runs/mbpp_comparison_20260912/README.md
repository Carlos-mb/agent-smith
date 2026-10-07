# MBPP 396: model and prompt comparison

Development runs requested by Carlos on 2026-09-12. Every candidate was generated
by the configured live API and executed through the normal CLI, persistent
worker, MCP stdio and Docker. Each result was checked with the available
`moulinette_eval validate mbpp`, including correctness and metrics. No reference
solutions or hidden tests were supplied to the agent. These repeated runs of one
task are development experiments, not an exam batch or the required SWE-bench report.

**Validated configuration:** `inclusionai/ling-3.0-flash-vl:free` with the original
prompt: **Correctness PASSED / Metrics VALID / Overall PASSED**. The original
prompt is restored in the application and matches this run's `system_prompt`
exactly. This is one successful sample; subsequent requests can behave differently.

| Run | Requested model | Prompt | Iterations | Input / output tokens | Seconds | Overall |
| --- | --- | --- | ---: | ---: | ---: | --- |
| [User baseline](../mbpp_20260912_053114/solution.json) | North Mini Code | Original | 5 | 5,333 / 1,029 | 9.9 (user report) | FAILED |
| [01](01_advanced_original_prompt/solution.json) | Inkling | Original | 1 | 0 / 0 known subtotals; usage missing | 0.72 | FAILED: HTTP 403 |
| [01b](01b_ling_original_prompt/solution.json) | Ling 3.0 Flash VL | Original | 4 | 3,237 / 388 | 7.39 | **PASSED** |
| [02](02_north_simple_prompt/solution.json) | North Mini Code | Simplified | 3 | 1,744 / 195 | 3.91 | FAILED |
| [03](03_auto_simple_prompt/solution.json) | openrouter/free | Simplified; reasoning disabled | 6 | 4,056 / 548 known subtotals; last usage missing | 7.14 | FAILED: HTTP 400 |
| [03b](03b_auto_default_reasoning/solution.json) | openrouter/free | Simplified; default reasoning | 2 | 1,246 / 991 | 7.02 | FAILED: response without text |
| [04](04_ling_simple_prompt/solution.json) | Ling 3.0 Flash VL | Simplified | 3 | 2,140 / 262 | 5.61 | FAILED |

All six new validations reported `Metrics: VALID`. For 01 and 03, this checks the
stored numerical subtotals; it does not establish complete accounting or zero
consumption for the rejected request. Each run directory retains `solution.json`,
`stdout.log`, `stderr.log` and `validation.log`. The public input is [task.json](task.json).

The user baseline incorrectly limited matching to strings of one or two
characters. The simplified-prompt North and Ling candidates incorrectly required
all characters to match. Both passed the two public assertions and failed
moulinette correctness. No handwritten solution replaced these failed outputs.

Inkling's free endpoint rejected this client as an unsupported agentic harness;
that restriction was not bypassed. Ling was selected explicitly as another larger
free model with `stop` support. In automatic run 03, the API reported Ling Sante,
North, Ling Sante, Ling VL and Ling VL, then rejected disabling reasoning on an
unreported model. In 03b it selected Ling VL and Ling Sante; the second response
contained no text completion. Each step records the API-reported model, falling
back to the requested ID when the API omits it.

The shorter prompt is preserved in [prompt_simplified.txt](prompt_simplified.txt);
the retained prompt is [prompt_original.txt](prompt_original.txt). Both include
the same discovered manual. Simplifying the prompt reduced consumption in these
samples but did not produce a correct solution. This small comparison does not
isolate randomness or establish a general ranking of prompts or models.

## Configuration and sources

- [Initial configuration](models_config.json) covers 01 through 03, including the
  rejected Inkling entry. [Corrected router configuration](models_config_router_default_reasoning.json)
  covers 03b and 04 and matches the final public configurations.
- [Public catalog snapshot](free_models_catalog.json) records zero prompt and
  completion prices and advertised `stop`/`max_tokens` support for the selected
  OpenRouter IDs. It does not establish access with a particular account.
- [Ling model](https://openrouter.ai/inclusionai/ling-3.0-flash-vl:free),
  [Inkling model and access restriction](https://openrouter.ai/thinkingmachines/inkling:free),
  [free router documentation](https://openrouter.ai/docs/guides/routing/routers/free-router).
  `openrouter/free` selects among free models randomly after capability filtering;
  it does not promise to choose the best coding model. Paid `openrouter/auto` was
  not used. Provider credentials were loaded from the local ignored `.env`.

## Reproduce the validated configuration

Run from `student/`, with Docker running and the existing environment prepared:

```bash
AGENT_SMITH_LOG_LEVEL=DEBUG \
AGENT_SMITH_MODELS_CONFIG=configs/models_template.json \
uv run --env-file .env --offline --no-sync --python 3.10 python -m agent_mbpp \
  --task-file benchmark_runs/mbpp_comparison_20260912/task.json \
  --output solution_ling.json \
  --model-name inclusionai/ling-3.0-flash-vl:free \
  --provider-url https://openrouter.ai/api/v1
```

Then, from `moulinette/`:

```bash
uv run --offline --no-sync --python 3.10 moulinette_eval validate mbpp \
  ../student/benchmark_runs/mbpp_comparison_20260912/task.json \
  ../student/solution_ling.json
```

These example output paths overwrite a previous manual rerun with the same name;
they leave the comparison evidence above intact. For uv cache permission errors,
prefix the commands with `UV_CACHE_DIR=/tmp/agentsmith-uv-cache`.
