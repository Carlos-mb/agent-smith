*This project has been created as part of the 42 curriculum by cmelero-.*

# Agent Smith

## Description

Agent Smith is a Python project for an autonomous code agent. It targets MBPP,
which contains small Python programming tasks, and SWE-bench, which requires
patches for issues in real repositories.

The agent follows `Thought -> Code -> Observation`: an LLM proposes Python code,
a separate worker executes it, and the agent uses the observed result to decide its
next step. Both benchmarks are implemented and validated with the moulinette; the
measurements are in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

[notes/GUIDE.md](notes/GUIDE.md) explains the project from the ground up: the
background concepts, how Agent Smith works inside, a SWE-bench task from start to
finish, and the lessons learned while building and measuring it; [notes/guide.html](notes/guide.html)
is the same guide as a web page. If you are about to start this project yourself, begin
with its "Before you start" section.

## Current status

Implemented: public JSON models and CLI arguments, restricted persistent Python
worker, process supervision, Python extraction, observations, MCP discovery and
wrappers through stdio and streamable HTTP, the interactive sandbox REPL, Docker
MBPP tests, configurable HTTP provider client, shared agent loop, and MBPP
adapter/CLI.

The controlled integration test runs the actual CLI, worker, MCP server and Docker
with scripted HTTP responses and known candidate code. It observes a failed test,
corrects the candidate, sees passing tests, then submits the persistent solution.
Its provider responses and token values are fixtures, not benchmark measurements.

The [model/prompt comparison](benchmark_runs/mbpp_comparison_20260912/README.md)
records all six new development attempts on the same task, including failures.
The reasons for retaining Ling and the original prompt are documented below.

Earlier unsuccessful OpenRouter/Gemini attempts remain in
[`benchmark_runs/mbpp_local_20260911`](benchmark_runs/mbpp_local_20260911), and the
[user's North baseline](benchmark_runs/mbpp_20260912_053114/solution.json) is also
preserved. Failures included API access/quota errors, incomplete code and incorrect
solutions despite passing public tests. These are development runs, not an exam batch.

The worker now receives `test_imports` and `test_list` before the agent loop. The
prompt asks for a short Thought and solution source in a raw triple-quoted string
to preserve backslashes. HTTP errors retain the provider's diagnostic message
while hiding configured keys. The input estimate has been corrected, temperature
defaults to 0.1 as in the reference, and missing-code feedback asks for the whole
block again. Each step now records the model reported by the API, which matters
when the explicitly selected free router changes models between requests.

The SWE-bench tools and adapter are implemented: the tools have their own
tests, and a controlled cycle test drives the real CLI, container, MCP
server and worker through exploration, an edit and `final_answer(get_patch())`.
Six SWE-bench tasks pass moulinette with at least one model
([evidence](benchmark_runs/swebench_20260914/README.md)), and the model
comparison is in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md). Extraction takes a closed
```python block first (when a reply holds several, the first one that calls a
discovered tool or `final_answer`) and otherwise converts two tool-call dialects into the
equivalent Python calls: `<tool_call>` with `<arg_key>`/`<arg_value>`, and
`<tool_use>` with `<tool_name>`/`<arguments>`. A provider's own `tool_calls`
field is rewritten into the second dialect in `providers.py` first, so a call
becomes Python in one place only. Each conversion tells the model in its
observation that the call was converted and executed. They are not optional in
practice: in a live SWE-bench run the selected model switched to a tool-call
dialect after its first observation, and every later iteration produced nothing
executable without them.
The subject's XML `<invoke>` and ReAct formats are still not handled; no model
used here has produced them.

## MBPP model selection history

**2026-09-17 initial choice:** We selected `inclusionai/ling-3.0-flash-vl:free` 
through OpenRouter because it passed moulinette on tasks 396 and 163 (evidence in
`benchmark_runs/mbpp_comparison_20260912/` and `benchmark_runs/mbpp_second_task_20260912/`).

**2026-09-29 update:** OpenRouter removed all free-tier models. 
`inclusionai/ling-3.0-flash-vl:free` is no longer available. We re-measured and
selected `gemini-3.5-flash-lite` through Google's generative API, which passed
five randomly drawn MBPP tasks out of five (2026-09-29). Gemini remains on Google's
free tier with no credit card required.

The [comparison evidence](benchmark_runs/mbpp_comparison_20260912/README.md)
includes all attempts, both prompts, configurations, model responses and
moulinette validations. These development samples support a practical starting
choice; they do not establish a general model ranking or guarantee passing the
exam.

At the user's request, we then drew another task at random using moulinette's
`dump mbpp` command and ran it once, with the same Ling configuration and the
identical system prompt. Task 163 asks for the area of a regular polygon. The
agent's first candidate passed its public tests through MCP/Docker, and its next
response submitted `final_answer(solution)`. Moulinette independently validated
the resulting JSON without `--skip-metrics`:

| Task | Iterations | Input tokens | Output tokens | Total time | Moulinette |
| --- | ---: | ---: | ---: | ---: | --- |
| 396: matching first/last characters | 4 | 3,237 | 388 | 7.389 s | PASSED / VALID / PASSED |
| 163: regular polygon area | 2 | 1,505 | 169 | 3.537 s | PASSED / VALID / PASSED |

Both runs used the limits of 10 iterations, 6,000 input tokens, 1,500 output
tokens and 120 seconds, including preparation and cleanup. The second run used
Python 3.10.12 for the CLI and moulinette, with Docker as configured. No candidate
was edited by hand and no model or prompt adjustment was made for task 163.
Its [evidence and commands](benchmark_runs/mbpp_second_task_20260912/README.md)
include the public task, full result, DEBUG exchanges and validator output.
Both tasks passed; this small development sample is not a benchmark pass rate.

## System architecture

One task uses three processes:

1. **The agent** (`agent_mbpp.py` / `agent_swebench.py`) owns the LLM client, the
   API keys, the task limits, the MCP client and the sandbox session. It runs the
   Thought → Code → Observation loop. All of its code is ordinary synchronous Python.
2. **The sandbox worker** (`agent_smith/sandbox.py`, started by
   `agent_smith/sandbox_session.py` with `multiprocessing`) executes the generated
   Python. It keeps one namespace, so variables persist between blocks. It talks to
   the agent through a `multiprocessing` Pipe, sending plain Python dictionaries. It
   clears its inherited environment on start, so it never sees API keys, and it owns
   no MCP session and no Docker client.
3. **An MCP server** (`mcp_tools_mbpp.py` or `mcp_tools_swebench.py`) performs the
   trusted work, such as running tests inside Docker. Tools are discovered from the
   connected server.

When generated code calls a tool, the worker sends an `mcp_request` and waits; the
agent calls the MCP server and sends back the `mcp_result`. Only one operation is
active at a time. If a block exceeds its time limit, the agent kills the whole
worker process, which no code inside it can catch (not even a bare `except:`), and a
new worker can be started with its variables lost.

### Why a separate worker process

The subject allows running untrusted code inside the agent process or in a separate
one. A separate process gives the simplest explanation for the two hardest
requirements: the API keys are in a different process from the generated code, and
a runaway block is stopped by killing its process rather than by raising an
exception that the code could catch.

### Why a thread for MCP

The official `mcp` SDK is async-only. Instead of making the whole agent async,
`MCPClient` runs an asyncio event loop in one background thread. A single coroutine
opens the session, waits until `close()` is called and closes it, because the SDK
must open and close its contexts in the same task. Every request is sent to that
loop with `asyncio.run_coroutine_threadsafe` and the caller simply waits for the
answer. The rest of the program never sees `async` or `await`.

## Agent loop and limits

Each iteration requests a response, records its actual text and token metrics,
extracts Python, executes it once and feeds the observation back to the LLM.
Missing code, interpretation of malformed blocks, execution failures and truncated
logs need explicit observations. `final_answer` ends the loop and supplies the
solution: Python source for MBPP or the complete patch for SWE-bench.

The subject and the available moulinette models specify these task limits:

| Benchmark | Iterations | Input tokens | Output tokens | Total time |
| --- | ---: | ---: | ---: | ---: |
| MBPP | 10 | 6,000 | 1,500 | 120 seconds |
| SWE-bench | 30 | 300,000 | 10,000 | 900 seconds |

Each request sends the system prompt, the task and as many recent exchanges as fit in
a budget: the remaining input allowance divided by the remaining iterations, never
fewer than the last six messages. The whole list is resent every iteration, so
keeping all of it costs quadratically: one SWE-bench run spent 296,410 of its 300,000
input tokens that way, with a single search observation accounting for 72,264 of
them. A fixed three-exchange window failed the other way: the model forgot it had
already edited a file and re-read the same ranges 22 times. Trimming never discards
what the result file records: `steps` keeps every response and observation in full.

Tokens accumulate across the task, including reasoning tokens where applicable.
The loop must accumulate each request's metrics once. Total requests include
retries. Each solution must retain the full system prompt, raw model responses,
executed code and observations required by the public output contract.

The client selects one URL/model configuration, reads its named environment keys,
and rotates only those keys on HTTP 429. Retries are bounded by `max_retries`,
time and remaining tokens. A response without complete usage ends the task with
known subtotals and an explicit error; its unknown consumption is never reported
as a measured zero. A 429 is the exception: a rate-limited request is rejected
before the model generates anything, so its missing usage is a known zero. The
client advances the key index and retries with the next key, which is what makes
a second key useful at all; it never invents tokens for the rejected attempt.
Note that a provider's free-tier quota is usually per account, so extra keys on
the same account do not add quota. Set `max_retries` to 0 for a run without
HTTP retries.

Before sending, the client estimates input size as UTF-8 bytes divided by four
(rounded up), plus chat framing headroom. This adapts the reference approximation
and replaces the initial estimate that counted every byte as a token and stopped
live runs too early. This remains an estimate,
not an exact remote tokenizer or a guarantee against crossing the input limit.
Only API usage goes into metrics. Actual excess usage is preserved and marks the
task failed. Reasoning subtotals already included in completion tokens are not
added twice. Fixed-model configurations request reasoning disabled and cap each
reply at 600 tokens, also bounded by the task's remaining output allowance.
The free router leaves reasoning at the selected model's default: some endpoints
reject disabling it. Reasoning tokens still consume the same task allowance.

`configs/models_template.json` contains ten explicitly selectable configurations,
chosen by cross-checking which models other passing projects reported against what the
free tiers still offer. Several models those reports relied on
(`openai/gpt-oss-120b:free`, `deepseek-v4-flash:free`, `glm-4.5-air:free`,
`qwen3-next-80b:free`) have since disappeared from OpenRouter's free tier.

Through Groq, with `GROQ_API_KEY`, `GROQ_API_KEY_2` and `GROQ_API_KEY_3`:

- `qwen/qwen3.8-27b` — **the SWE-bench model.** It is the only model that solves
  `sympy__sympy-14711` reliably (five of five attempts), passed all six tasks measured
  and scored 3/3 in a full three-task run ([benchmark report](BENCHMARK_REPORT.md),
  section 6). Groq's free tier allows 8,000 tokens per minute, 7,000 input tokens per request
  (`max_input_per_request: 6000` keeps it below) and 200,000 per day per
  account, so its requests are often refused with HTTP 429 and the client waits as long
  as `retry-after` asks, switching to the key available soonest. It runs with
  `reasoning_effort: "none"` and 10 retries.

Through Mistral's API, with `MISTRAL_API_KEY` and `MISTRAL_API_KEY_2`:

- `codestral-2508` — **the first SWE-bench backup.** It is the most efficient model in
  the report (14 iterations and 34,139 input tokens on the matrix) and scored 3/3 in
  three of four full three-task runs; it solves `sympy__sympy-14711` only about one
  time in nine (report section 6).
  It stops at `<end_code>` and at `Observation:`; without the second stop it invented
  tool output until its token budget ran out (report section 5.4). On the free tier
  checked on 2026-09-15, `mistral-medium`, `mistral-small` and `devstral-medium` had a
  limit of zero requests per minute and `mistral-large` was not included.

Through Google's OpenAI-compatible endpoint, which has its own daily quota:

- `gemini-3.5-flash-lite` — **the MBPP model since 2026-09-29, and the second SWE-bench
  backup.** It passed 3/3 in the benchmark report, 2/3 twice in full three-task runs
  (it has never passed `sympy__sympy-14711`) and five random MBPP tasks out of five.
- `gemini-3.1-flash-lite`, `gemini-3.5-flash` and `gemini-3.8-flash` — measured in the
  report and discarded.

Through OpenRouter, on the free tier (on 2026-09-29 OpenRouter stopped offering
these models for free):

- `dots-studio/dots-3-note-preview:free` — **the third SWE-bench backup.** It passed
  3/3 in the report and passed `sympy__sympy-14711` once.
- `nvidia/nemotron-3.5-lightning:free` and `google/gemma-4-31b-it:free` — measured in
  the report and discarded (0/3).

To run each benchmark with its selected model, pass `--model-name qwen/qwen3.8-27b
--provider-url https://api.groq.com/openai/v1` to `agent_swebench`, and
`--model-name gemini-3.5-flash-lite --provider-url
https://generativelanguage.googleapis.com/v1beta/openai` to `agent_mbpp`. Without
`AGENT_SMITH_MODELS_CONFIG`, both agents read `configs/models_template.json`.

Some free models do not support the `stop` parameter. The client only requests it
when a stop sequence is actually configured in the model entry, to avoid excluding
those models from provider routing.

Availability and quotas can change. The project requires free access without
purchased credits or billing-enabled accounts. Extra keys do not imply extra
account/project quota. Provider selection remains explicit. Selecting
`openrouter/free` delegates model selection to OpenRouter; the program itself
does not switch configurations after a failure. Paid `openrouter/auto` is not used.

## Sandbox design

The first version implements standard-library controls for imports, explicit
builtins, file opening, exposed socket entry points, worker memory (`RLIMIT_AS`),
execution time and output. `RLIMIT_AS` bounds virtual address space, not exactly
resident RAM. Limits must apply successfully before the worker announces ready.

Path checks must resolve paths and check directory membership. An empty
`allowed_directories` list permits no access through the controlled file-opening
interface. File descriptors and options that bypass that interface must be
rejected. Restricted imports and a wrapper around `open` do not control every
operation that an allowed Python library can expose.

The worker's code timeout excludes time waiting for MCP. The total task deadline
includes those waits. Already received output must survive timeout or failure;
output truncation is reported. The final answer and the git patch are preserved
in full.

`final_answer` is always local to the sandbox and is never an MCP tool. A
`SystemExit` or `KeyboardInterrupt` raised by the generated code is an ordinary
error in the observation: it does not stop the worker or the agent.

These controls do not establish resistance to hostile Python introspection,
filesystem races, or alternative library APIs. Passing the subject's security
evaluation remains uncertain. The current project instructions authorize
Agent Smith and moulinette tests, including their generated Python, in the normal
project environment with Docker where configured. Extra isolation is not a
prerequisite for those tests. This authorization does not extend to unrelated
actions on personal files or credentials. Landlock, Linux
namespaces, mounts, `chroot`, capability manipulation and their prerequisite probes
are outside the chosen first version.

## MCP and tools

The MCP client supports stdio and streamable HTTP, dynamic discovery of tools,
resources and prompts, and a manual generated from server metadata. The SDK and
server validate MCP operations. The worker sees simple callable wrappers that ask
the agent through the Pipe; it does not own the MCP session.

The MBPP MCP server exposes `run_tests(code, test_imports, test_list,
timeout_seconds)`. Its helper runs the candidate and the public assertions with
one `docker run --rm --network none --memory 128m` command, bounded by the
remaining task deadline; on a timeout it removes the container with `docker rm -f`.
Each container has an unpredictable task label; after closing MCP, the adapter also
removes containers with that exact label to cover Ctrl+C or server death. Five
seconds of the total task limit are reserved for cleanup. Both benchmarks talk to
Docker the same way: through the `docker` command.

The SWE-bench server exposes one command helper and the nine required tools:

- `read_file(filepath, start_line, end_line)`
- `edit_file(filepath, old_str, new_str)`
- `list_files(directory, pattern)`
- `search_code(pattern, file_pattern)`
- `search_function_or_class_definition_in_code(name)`
- `find_references(name, filepath, line)`
- `run_tests()`
- `get_patch()`
- `run_command(command, workdir)`

All nine run where the checkout lives. With `AGENT_SMITH_CONTAINER_ID` the helper
uses `docker exec` inside that task container; otherwise it works on the host
directory named by `TESTBED_PATH`, which lets the tools be tested without a
container.
Paths are always exchanged as `/testbed/...` and mapped onto the real root, so the
model sees the same layout either way and cannot reach outside it. `run_tests`
executes the supplied `eval_script`; `get_patch` returns the complete diff and is
never truncated. Reference search is textual and cannot reliably distinguish all
usages of symbols with the same name.

`SWEEnvironment` owns exactly one container per task: it makes the task image
available, runs it with `--network none` holding `/testbed`, and exports only the
container name, the eval script and the deadline to the MCP server.

The container's lifetime is tied to the agent's own standard input. It runs as
`docker run -i --rm ... cat`, holding the write end of that pipe. Closing the pipe
is what stops it, so a normal exit, a cancellation and a `kill -9` all remove the
container: the kernel closes the agent's descriptors, `cat` reaches end of input,
the container stops and `--rm` deletes it. A `finally` alone cannot survive SIGKILL,
which is why the container is not kept alive with `tail -f /dev/null`. Verified by
killing the real CLI mid-task and checking `docker ps`. `run_swebench_agent` reuses the same `run_agent_loop` as MBPP; only the
prompts, limits and resource lifecycle differ.

## Instructions

Use Python 3.10 and uv. Run commands from the `student` directory. For an initial
environment setup, install the dependencies declared in `pyproject.toml` with
`uv sync --python 3.10`. No API provider is needed to inspect CLI help:

```bash
uv run --offline --no-sync --python 3.10 python -m agent_mbpp --help
uv run --offline --no-sync --python 3.10 python -m agent_swebench --help
```

The required task flags are `--task-file`, `--output`, `--model-name` and
`--provider-url`. Sandbox arguments retain an optional configuration path and
mutually exclusive `--mcp-stdio` and `--mcp-server` options. The sandbox opens
its worker and optional MCP client, and closes both on exit:

```bash
uv run --offline --no-sync --python 3.10 sandbox
uv run --offline --no-sync --python 3.10 sandbox configs/sandbox_template.json
uv run --offline --no-sync --python 3.10 sandbox \
  --mcp-stdio "python mcp_tools_mbpp.py" configs/sandbox_template.json
uv run --offline --no-sync --python 3.10 sandbox \
  --mcp-server http://127.0.0.1:8000/mcp
```

Type Python code at the prompt. A block ends with a blank line, exactly as in the
standard Python REPL, so an `else`, `except` or `finally` clause stays in the same
entry. An exact `exit` at the main prompt or EOF closes the sandbox. Piped input
(`cat file | uv run sandbox`) is read whole and executed one top-level statement at
a time. Entries share the
worker namespace. A fatal worker error restarts it and reports that variables
were lost. `final_answer` is printed and then the REPL continues.

### First live MBPP run

Use the normal project environment and its configured Docker daemon. The worker's
environment contains no API keys or Docker configuration; the agent loads
provider keys. Install dependencies with `uv sync --python 3.10` and prepare the
Docker image with `docker pull python:3.11-slim`, the same image moulinette uses. Keep provider keys in the local,
gitignored `.env`, based on `.env.example`. The program reads environment variables;
`uv --env-file` loads the file for the run.

1. In the moulinette directory: `uv run --python 3.10 moulinette_eval dump mbpp --output ../cache/mbpp/live_task.json`.
2. In the student directory:

```bash
AGENT_SMITH_MODELS_CONFIG=configs/models_template.json \
uv run --env-file .env --offline --no-sync --python 3.10 python -m agent_mbpp \
  --task-file ../cache/mbpp/live_task.json \
  --output ../cache/mbpp/live_solution.json \
  --model-name gemini-3.5-flash-lite \
  --provider-url https://generativelanguage.googleapis.com/v1beta/openai
```

3. In the moulinette directory: `uv run --python 3.10 moulinette_eval validate mbpp ../cache/mbpp/live_task.json ../cache/mbpp/live_solution.json`.

Do not pass `--skip-metrics`. Keep both JSON files and the validator's output,
including failures. CLI exit code 0 means a result JSON was written; inspect its
`success` and `error`. Only moulinette validation decides benchmark correctness.

### Logging

Logging is disabled when `AGENT_SMITH_LOG_LEVEL` is unset or empty. To see the
execution as it happens, add this line to your local `.env` and run with
`uv run --env-file .env` as above:

```dotenv
AGENT_SMITH_LOG_LEVEL=DEBUG
```

Alternatively, prefix an existing command with `AGENT_SMITH_LOG_LEVEL=DEBUG`.
Remove the variable or leave it empty to return to silent execution. The accepted
levels are `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL` (case-insensitive).
An invalid nonempty level reports a configuration error and uses `ERROR`.

Messages are in Spanish and include time, process ID, module, function and line:

- `DEBUG`: function/method entry, decisions, provider parameters and HTTP status,
  token/time budgets, full prompts, model responses, executed code, observations,
  worker messages, MCP operations and Docker cleanup.
- `INFO`: task stages, iterations, requests, test results and completion.
- `WARNING` / `ERROR`: rejected operations, failed tests, retries, limits and errors.

Detailed exchanges have these DEBUG labels:

- `IA ENVIADO`: every message in each HTTP attempt, with its role and full text,
  including previous answers and observations sent back to the model.
- `IA RECIBIDO`: the full HTTP response body, including errors and non-JSON bodies.
- `MCP ENVIADO` / `MCP RECIBIDO`: operation arguments and complete SDK results,
  including initialization, discovery and tool errors.
- `DOCKER ENTRADA` / `DOCKER SALIDA`: the actual Python program (candidate,
  imports and assertions), exit code and combined stdout/stderr. On a timeout,
  `DOCKER SALIDA PARCIAL` shows whatever output could be recovered. DEBUG records
  the received Docker output before the existing observation truncation.

The agent, the worker and the bundled MCP servers write logs to **stderr**, in real
time. With `DEBUG` they also append every record to one shared file, so a whole run
can be read afterwards: `logs/agent_smith_<date>_<time>.log` under the directory the
command runs from, or the path in `AGENT_SMITH_LOG_FILE`. The agent chooses the file
name when it starts and passes it on to the worker and the MCP server; each line shows
the process ID that wrote it. Code output returned as observations and result files
keep their format; diagnostic logs do not become model observations. Handled CLI errors follow the
selected log level and retain their exit codes. Explicit `--help` still prints help.

Configured provider keys are redacted from agent logs, and HTTP headers and
third-party SDK logs are excluded. DEBUG still includes the task's full text and
generated code. Only the log level and the log file name are forwarded to the worker
and MCP server; provider keys remain in the agent.

### Tests

From the student directory:

```bash
uv run --offline --no-sync --python 3.10 python -m pytest tests/test_sandbox_session.py tests/test_providers.py tests/test_agent_loop.py
uv run --offline --no-sync --python 3.10 python -m pytest tests/test_sandbox_cli.py tests/test_mcp_client.py
uv run --offline --no-sync --python 3.10 python -m pytest tests/test_mbpp_cycle.py tests/test_mcp_mbpp.py tests/test_mbpp_tools.py
git diff --check
```

The second command needs Docker and the prepared image. Check skipped tests;
a skipped Docker test does not prove integration. `test_mbpp_cycle.py` uses fake
HTTP responses, actual processes and Docker, including Ctrl+C during tests.
If the default uv cache is read-only, prefix commands with
`UV_CACHE_DIR=/tmp/agentsmith-uv-cache`; this does not change the interpreter.
Reserve the full suite for integration work.

The moulinette includes public models and benchmark validation code. Tests,
moulinette validation and the evaluation scripts are distinct: passing one does
not prove the others. On 2026-09-12, the full integration suite passed
**198 tests in 26.44 seconds**, with Python 3.10.12 and Docker, without skips.
This includes logging levels, silence by default, key redaction, clean JSON
channels and controlled correction in both silent and DEBUG modes. No Agent Smith
MBPP containers remained after these tests. No live API request or moulinette
validation was repeated for this logging change. These tests do not prove a live
benchmark pass. The available
moulinette CLI runs under Python 3.10; its candidate-test image is `python:3.11-slim`,
while the agent's Docker tests use `python:3.10.12-slim`.

The subsequent DEBUG exchange expansion passed **77 focused tests in 14.34
seconds**, with Python 3.10.12 and Docker. Those checks cover full request history,
HTTP response bodies, redaction, MCP payloads and complete/partial Docker output;
the full suite was not repeated for this smaller change.

After adding API-reported model names for router requests, 21 provider/loop tests
passed in 11.90 seconds. The focused provider/loop/CLI/worker/MCP/Docker integration
passed 25 tests in 16.54 seconds while evaluating the simplified prompt. The
original prompt was then restored and checked against the successful live run's
full system prompt. Every new live result was validated by moulinette separately;
the public configurations were parsed and their router payload checked offline.
After restoring the original prompt, all 4 tests in `test_mbpp_cycle.py` passed
in 5.39 seconds with Docker, checking the final code's controlled correction cycle.

After adding the REPL and streamable HTTP transport, the full suite passed
**217 tests in 29.68 seconds** with the Python 3.10 command above. The HTTP test
starts a local FastMCP server, discovers an unknown tool, resource, resource
template and prompt, then calls them through the real worker wrappers. The REPL
tests cover multi-line input, persistence, syntax errors, EOF and recovery after
a lost worker. No live provider request or moulinette validation was run for this
change.

## Benchmark results and analysis

The [benchmark report](BENCHMARK_REPORT.md) compares ten models on the same
three SWE-bench tasks, with provider reliability, two intermediary metrics and
six ablations. `qwen/qwen3.8-27b` is the selected model, with `codestral-2508`,
`gemini-3.5-flash-lite` and `dots-studio/dots-3-note-preview:free` as backups on
three other providers.
Every figure is read from a `solution.json` kept under `benchmark_runs/`.

## Resources and AI assistance

Project requirements come from the supplied `en.subject.pdf`, with public JSON
contracts and validation limits checked against the available moulinette code.
Useful primary references for implementation are:

- [Python 3.10 documentation](https://docs.python.org/3.10/), especially `multiprocessing`,
  `asyncio`, `subprocess`, `pathlib` and `resource`.
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) for MCP
  sessions, transports and server capabilities.
- [Pydantic documentation](https://docs.pydantic.dev/latest/) for data models.
- [OpenAI Python SDK](https://github.com/openai/openai-python) for the
  OpenAI-compatible chat-completions requests to every provider.
- [Docker CLI reference](https://docs.docker.com/reference/cli/docker/) for
  `docker run`, `exec` and `rm`.
- [uv documentation](https://docs.astral.sh/uv/) for the Python environment.

AI assistance covered inspecting the reference and subject, implementing the MBPP
worker/supervisor, MCP lifecycle, provider client, shared loop and adapter, writing
controlled tests, running live-provider development attempts and moulinette
validation, and updating documentation. Carlos must understand and defend these
changes. Recorded failures and measured usage are preserved; no evaluation pass
is claimed.