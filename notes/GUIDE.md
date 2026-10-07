# Agent Smith Guide

## Contents

**Before you start** — what the project asks of you, an order of work that keeps frustration low, and advice.

**Part I. Background concepts**

1. **What a coding AI agent is** — the Thought → Code → Observation loop.
2. **What an agent framework is** — and why this project cannot use one.
3. **Talking to an AI model through an API** — messages, tokens, `usage` and HTTP status codes.
4. **Common problems with free APIs** — limits, quotas and unusual responses.
5. **What MCP is** — servers, clients, tools and transports.
6. **What a sandbox is** — running someone else's code safely.
7. **Processes and inter-process communication** — pipes, signals and asynchronous programming.
8. **Docker essentials** — images, containers and orphaned containers.
9. **What MBPP is** — short Python exercises with tests.
10. **What SWE-bench is** — real issues from real projects.
11. **How an agent is evaluated** — metrics, comparisons and ablations.

**Part II. Inside Agent Smith**

12. **What the subject asks for** — the requirements, listed.
13. **The working environment** — the repository and the moulinette.
14. **The three commands** — what each one is for and which processes it starts.
15. **Architecture: three processes** — what each one does and what it cannot see.
16. **How the processes communicate** — the messages and the journey of a tool call.
17. **An MBPP task step by step** — from the command to the result file.
18. **What changes for SWE-bench** — container, tools and patch.
19. **The loop in detail** — limits, counters, errors and the model's memory.
20. **Design decisions** — what was chosen, over what, and why.
21. **Extracting code from the response** — the requested format and the ones that arrive.
22. **Sandbox controls** — what is restricted, how, and what is left out.
23. **Docker in Agent Smith** — one container per test run, one per task, and `kill -9`.
24. **The provider** — model selection, keys, retries and usage.

**Part III. A SWE-bench task from start to finish**

25. **SWE-bench from start to finish** — from the task and the image to validation, with a real example.

**Part IV. Lessons learned**

26. **Free models in practice** — catalogues that change, quotas and what each refusal means.
27. **Choosing a model** — what a comparison of ten models showed, and how far to trust it.
28. **What measuring the agent taught** — where iterations go, and which changes helped.
29. **Bugs that looked like model failures** — and how replaying saved runs exposed them.
30. **Running on shared machines with rootless Docker** — disk, images, CPU limits and file owners.
31. **Stopping the agent** — every way of killing it, and what happens to the container.
32. **A working method** — habits that saved time.

---

# Before you start

## What you will face

- **A project with many moving parts.** Three commands, three cooperating processes, an MCP server
  for each benchmark, Docker, a provider client with several keys, usage tracking, and a benchmark
  report comparing at least five models, with an ablation. Agent Smith ended up at about 3,800
  lines of Python, tests not included. Most of the time does not go into writing code: it goes into
  understanding how the pieces talk to each other, waiting for providers and measuring.
- **Two benchmarks of very different size.** An MBPP task is one small function, with 10
  iterations, 6,000 input tokens and 120 seconds. A SWE-bench task is a real bug in a real project,
  such as django or sympy, inside a Docker image of several gigabytes, with 30 iterations, 300,000
  input tokens and 900 seconds (section 12).
- **Free models only.** Quotas, waits, empty answers and models that disappear from one week to the
  next are part of the work, not accidents (section 26). The subject forbids paying, so there is no
  shortcut.
- **Disk space and downloads.** Each SWE-bench image takes between 4 and 7.6 GB, and you will want
  several. On the school machines Docker runs rootless and needs some setup first (section 30).
- **How the work is checked.** The moulinette validates the `solution.json` files your agent
  writes, both the answer and the metrics; it never runs your code (section 13). The project is
  also tested with scripts that exercise the sandbox and run the agent on MBPP tasks and on
  SWE-bench tasks from real repositories. In the evaluation you explain your own design, and the
  subject warns that you will make small changes to your agent on the spot. Every line has to be
  one you understand.
- **Every number must be real.** Token counts come from what the provider reports, and the report
  needs the `solution.json` files behind its figures (section 12.7).

## An order of work that keeps frustration low

Each step can be tested before the next one exists, so when something fails there is only one new
piece to suspect.

1. **Read the subject's data models and limits** (section 12), and make the agent write its result
   file from the first day, also when a task fails. A run that crashes before writing it is worth
   nothing.
2. **Build the sandbox without any model.** The worker process, its restrictions and the `sandbox`
   command (section 14.2) can be tested with code you type yourself.
3. **Add MCP with the smallest server you can write**: one tool that adds two numbers, first over
   stdio, then over HTTP. Then generate the manual from its schema (section 5.6).
4. **Write the MBPP tool and try it without a model**: give it a correct function and a wrong one,
   and read what it answers.
5. **Only then connect a model**, on one MBPP task, and validate the result with the moulinette.
   Keep that task as a quick check after every change.
6. **For SWE-bench, test the nine tools by hand before writing the loop**: start a task container,
   then read, search, edit, run the tests and get the patch. Tools that can also work on a plain
   folder are much easier to test (section 23.2).
7. **Run the SWE-bench loop on an easy task first**, such as the one in section 25.
8. **Keep every `solution.json` from the beginning.** Each one is a future data point for the
   report, and replaying them finds bugs (sections 29.1 and 32).

## Advice that saves frustration

- **Keep the code small and synchronous.** You will have to explain all of it. The official MCP SDK
  is asynchronous, so keep that part inside the MCP client (section 15.2). Use the provider's
  official SDK with its own retries disabled, so that you count every request (section 24.3).
- **Write tests with scripted model replies**, so the test suite never spends quota and always gives
  the same result.
- **When something goes wrong, log everything to a file.** Read the model's reply (`llm_output`)
  next to the code that actually ran (`sandbox_input`): several "model failures" in this project
  were bugs in the agent (section 29).
- **Get keys from several providers in the first week**, and check each model with one request
  before relying on it (section 26.1).
- **Configure stop sequences for each model** and look at the first replies of any new model: an
  invented `Observation:` means a stop sequence is missing (section 28.3).
- **Download the Docker images before you need them**, and check the free disk space first
  (section 30).
- **Do not chase a single failure.** Free models vary from hour to hour; run again before changing
  code (sections 26.5 and 27.3).
- **Never add a payment method to a provider account** (section 26.4).
- **Write the README's description of how you used AI as you go**, honestly. The subject asks for
  it, and it is much easier than reconstructing it at the end.

---

# Part I. Background concepts

This part explains general ideas that do not depend on Agent Smith. It is worth reading before
Part II, which assumes them.

## 1. What a coding AI agent is

### 1.1 From a question to an agent

A **language model** (LLM, *Large Language Model*) is a program that, given some text, generates
the most likely continuation. When used as a chat, a person asks, the model answers, and the
interaction ends there: the model does not check whether its answer works.

An **agent** adds what that scheme lacks: the ability to **act and observe the result**. The model
proposes an action, a program executes it, and the result goes back to the model so it can decide
the next step. This way it can explore, make mistakes, correct itself and check its work before
declaring it finished.

### 1.2 The Thought → Code → Observation loop

In this project the agent's actions are **Python code snippets**. Each turn of the loop has three
parts:

| Part | Produced by | What it is |
| --- | --- | --- |
| **Thought** | The model | A short sentence about what it will do and why |
| **Code** | The model | A Python block that performs that action |
| **Observation** | The program | What happened when the code ran: what it printed, or the error |

The observation is added to the conversation, and the model writes its next thought based on it.
Each complete turn is called an **iteration**.

An example, for an exercise that asks for a function that adds two numbers:

1. *Thought*: "I will write the function and check it against the tests."
   *Code*: defines the function and calls a tool that runs the tests.
   *Observation*: "All tests pass."
2. *Thought*: "The tests pass; I will submit the solution."
   *Code*: calls the final-answer function with the solution code.

### 1.3 Why code and not just text

Another common way to give tools to a model is to have it reply with a JSON object naming the tool
and its arguments. Writing Python is more expressive: it can store a result in a variable and use
it in the next turn, chain several calls in a single iteration, or use conditions and loops.

The downside is that this code was written by a model and must be run with care. Section 6 covers
that.

### 1.4 How it ends

The loop ends in one of two ways:

- **Final answer.** The model calls a special function that delivers the result. In this project
  it is called `final_answer`: it receives the solution as text and signals that the task is
  finished.
- **A limit is reached.** Maximum number of iterations, tokens (section 3) or time. Without limits,
  an agent that cannot find the solution could go on indefinitely.

## 2. What an agent framework is

### 2.1 Library versus framework

A **library** is code your program calls when it needs it: you decide the order and the flow. A
**framework** reverses that relationship: it defines the program's structure and overall flow, and
you write the pieces it calls at the right moment.

### 2.2 Agent frameworks

An **agent framework** is a framework that already solves the loop from section 1: how the model
is called, how its actions are extracted and executed, how the conversation is stored and how
tools are registered. Its users only configure the model, write the prompt and declare their
tools. Well-known examples are LangChain and LangGraph, LlamaIndex, smolagents, CrewAI and
AutoGen.

### 2.3 Why it matters in this project

The goal of the project is precisely to **build that loop**. That is why the subject forbids any
library that re-implements agent orchestration: the agent loop must be your own code.

Libraries that solve other parts are allowed, such as a provider's official API client or the MCP
SDK (section 5): they do not decide the agent's flow.

## 3. Talking to an AI model through an API

### 3.1 Request and response

Provider models (Mistral, Google, Groq, OpenRouter…) do not run on your computer: they are used
through an **API**, a web address to which the program sends an HTTP request with a JSON body and
from which it receives a response, also in JSON.

Many providers imitate the format of OpenAI's API called **chat completions**. That is why they are
called "OpenAI-compatible": the same program can talk to all of them by changing only three
things.

- **Base URL**: the provider's address, for example `https://api.mistral.ai/v1`.
- **Model name**: which of its models you want to use.
- **API key**: a secret string that identifies your account. Anyone who has it can spend your
  quota, so it is never written in the code: it is stored in a `.env` file, which is not committed
  to the repository, and the program reads it from **environment variables**.

An **SDK** is a library a provider publishes so that you do not have to build HTTP requests by
hand. OpenAI's official SDK works with any compatible provider.

### 3.2 Messages and roles

The request contains a list of **messages**, each with a role:

| Role | Content |
| --- | --- |
| `system` | The **system prompt**: general instructions, response format, available tools |
| `user` | What the model receives: the task and, in an agent, the observations |
| `assistant` | What the model answered in previous turns |

**The model remembers nothing between requests.** For it to know what happened before, the
program resends the whole conversation with every request, or the part it decides to keep. This
has a direct consequence on cost, explained next.

### 3.3 Tokens

Models do not work with letters or words but with **tokens**: text fragments a few characters
long. As a rough guide, in English one token is about four characters.

- **Input tokens**: those of all the messages sent in the request.
- **Output tokens**: those the model generates in its response.

Limits and quotas are measured in tokens. Since the conversation is resent in full, a long
observation is not paid for once: it is paid for in every later request while it stays in the
history.

Some models, called **reasoning models**, also generate internal text before answering. Those
tokens count as output too.

### 3.4 Request parameters

- **Maximum output tokens**: cuts the response when that number is reached.
- **Temperature**: how much randomness goes into choosing each token. A low value gives more
  stable answers.
- **Stop sequences** (`stop`): strings that end the response when generated. In an agent they are
  essential. Without them, the model writes its code and **keeps writing an invented
  observation** instead of waiting for the real one.

### 3.5 The response and the `usage` block

A successful response contains, among other fields:

- the generated **text**;
- the **model** that actually answered, which may differ from the one requested (section 4.4);
- the **`usage`** block, with the input tokens (`prompt_tokens`) and output tokens
  (`completion_tokens`) the provider has counted.

`usage` is the only reliable measure of consumption. A program can estimate tokens before
sending, but an estimate is not a measurement.

### 3.6 HTTP status codes

Every HTTP response carries a number that summarises what happened:

| Code | Meaning | What is usually done |
| --- | --- | --- |
| **200** | Success: the model generated a response | Read the text and `usage` |
| **400** | Malformed request (unsupported parameter, invalid message) | Fix the request; retrying does not help |
| **401 / 403** | Invalid key or no permission for that model | Check the key or the plan |
| **404** | The model or path does not exist | Check the model name; it may have been retired |
| **413** | The request is too large for that model or plan | Send a smaller request; waiting does not help |
| **429** | Too many requests or quota exhausted | Wait or use another key |
| **500 / 502 / 503 / 504** | Provider error or overload | Retry after a moment |

There are also failures with no code: a **timeout**, when the response does not arrive within the
maximum time, and a **lost connection**.

An important distinction for measuring correctly: on a 4xx or 5xx the provider is taken to have
**rejected the request without generating a response**, so no tokens were consumed. On a timeout
you cannot know: the model may have generated a response that never arrived.

### 3.7 Retries and `retry-after`

**Retrying** means repeating a request that failed for a transient reason. Each retry is one more
request, and must be counted as such.

On a 429, many providers send a **`retry-after`** header saying how many seconds to wait before
trying again.

## 4. Common problems with free APIs

Free plans let you develop without paying, but they impose restrictions an agent must withstand
without breaking.

### 4.1 Usage limits

Providers limit usage along several dimensions at once, and any of them triggers a 429:

| Limit | Usual abbreviation | Typical effect |
| --- | --- | --- |
| Requests per minute | RPM | Many quick turns in a row |
| Tokens per minute | TPM | Few requests, but very long ones |
| Requests per day | RPD | Exhausted after a long testing session |
| Tokens per day | TPD | The same, measured in tokens |

Four details worth knowing:

- **Per account, per project or per key.** The limit usually belongs to the account (or, with some
  providers, to the project the key was created in): several keys from the same account share the
  quota. To spread the load you need keys from different accounts or projects.
- **Key rotation.** Switching to another key when one receives a 429. It only helps if the keys
  have independent quotas.
- **Daily quotas do not always reset at midnight.** Some providers replenish them continuously: with
  1,000 requests per day, one request comes back every 86.4 seconds. Waiting until "tomorrow" then
  gains nothing.
- **A per-request ceiling is a different limit.** Besides tokens per minute, a plan may refuse any
  single request above a size. That refusal (often a 413) is permanent for that request: only a
  smaller request gets through.

### 4.2 Models change

On free plans, available models and their conditions change without notice: a model disappears,
becomes paid or has its limit reduced. An agent that worked may stop working without a single line
of code changing. That is why it pays to be able to switch models by editing only the
configuration, and to check it before relying on it.

### 4.3 Unusual responses

Free models produce responses that documentation rarely mentions:

- **Empty responses**: status 200, but no text.
- **Responses without `usage`**: the model generated something, but its cost is unknown.
- **Tool calls in another format**: the model does not write the requested Python block but the
  call format it was trained on, or uses the API's own function-calling channel.
- **Invented observations**: the model writes what it thinks its code will return instead of
  waiting (section 3.4).
- **Excessive reasoning**: a reasoning model may spend much of its output allowance before writing
  the answer.

### 4.4 Routers

Some services, such as OpenRouter, do not host models: they forward the request to other
providers. The model that answers may not be exactly the one requested, and the response says so
in its model field. That is why it is worth recording the model that answered, not just the one
requested.

### 4.5 Consequence for the design

An honest agent **measures what it consumes and does not invent it**. If it does not know how much
a request cost, it must say so instead of recording a zero. And each kind of failure needs a
different response: wait, switch keys, retry or stop.

## 5. What MCP is

### 5.1 The problem it solves

An agent needs tools: reading files, searching code, running tests. If every agent defines them
its own way, they cannot be reused. **MCP** (*Model Context Protocol*) is an open protocol that
standardises how a program offers capabilities to a language model.

### 5.2 Server and client

- An **MCP server** is a program that **offers** capabilities.
- An **MCP client** is the part of the agent's program that **connects** to a server, asks what
  it offers and asks it to perform operations.

The server does the work. The client only relays requests and results.

### 5.3 What a server can offer

| Capability | What it is | Example |
| --- | --- | --- |
| **Tools** | Functions with a name, description and parameters | `run_tests(code, test_list)` |
| **Resources** | Data identified by an address (URI) | A configuration file |
| **Prompts** | Reusable text templates | A predefined instruction |

Each tool publishes a **schema** in JSON Schema format: which parameters it accepts, their types,
which are required and their default values.

### 5.4 Discovery

MCP's central feature is that **the client does not need to know the server in advance**. When it
connects, it asks which tools, resources and prompts exist and receives their schemas. A well-built
agent works with a server it has never seen.

### 5.5 Transports

MCP defines how messages travel between client and server:

- **stdio**: the client starts the server as a child process and they communicate through its
  standard input and output (section 7). It is the natural choice for a local server.
- **Streamable HTTP**: the server is already running and listens on a URL, local or remote.

Messages follow the **JSON-RPC** format, which defines standard error codes. Two of them matter
here: **-32601** (the method or tool does not exist) and **-32602** (invalid parameters). Both mean
the caller made a mistake, not that the server failed.

### 5.6 The manual

With the discovered schemas, the agent can generate a **manual**: text with each tool's name,
description and parameters. That manual goes into the system prompt so the model knows what it
can call and how. If another server is connected, the manual changes by itself.

## 6. What a sandbox is

### 6.1 The risk

An agent runs code written by a model. That code may be wrong or, in the worst case, harmful:

- deleting or reading files it should not;
- connecting to the internet, for example to look up the solution or leak data;
- never finishing, like a `while True`;
- consuming all the computer's memory;
- reading the agent's own API keys.

A **sandbox** is an execution environment that limits what that code can do.

### 6.2 Kinds of controls

| Control | What it prevents |
| --- | --- |
| **Allowed imports** | Loading dangerous modules such as `os`, `subprocess` or `socket` |
| **Restricted builtins** | Using built-in functions such as `eval`, `exec` or `open` without control |
| **Allowed directories** | Reading or writing outside specific folders |
| **No network** | Opening connections |
| **Time limit** | Blocks that never finish |
| **Memory limit** | Exhausting memory |

**Builtins** are the functions Python offers without importing anything (`print`, `len`, `open`,
`eval`…). They can be replaced with a reduced list.

### 6.3 Isolating with a process

There is an important difference between running the code in a **thread** or in a separate
**process** (section 7):

- A **thread** shares memory with the main program and, in Python, **cannot be stopped from
  outside**. If the code enters an infinite loop, the thread keeps running.
- A **process** has its own memory, and the operating system can terminate it at any moment. It
  also cannot see the main program's variables.

That is why isolating in a separate process makes a real time limit possible.

### 6.4 Limits of a sandbox written in Python

Restricting imports and builtins from within Python is useful, but it is not an absolute barrier:
a determined attacker can explore the language's internal objects to recover blocked functions.
Strong barriers come from the operating system or a container. A sandbox built only with the
standard library is reasonable for code from a model trying to solve a task, as long as its limits
are understood.

## 7. Processes and inter-process communication

### 7.1 Processes

A **process** is a running program with its own memory. A process can create others, called
**child processes**. Each one has its own **environment**: a copy of the environment variables,
which its parent can prepare before starting it. This is how you decide which secrets each process
can see.

### 7.2 Standard input and output

Every process has three text channels: **standard input** (*stdin*), **standard output**
(*stdout*) and **standard error** (*stderr*). A parent process can connect to its child's channels
to send it data and read what it writes.

### 7.3 Pipes

A **pipe** is a channel through which one process writes and another reads. It has a very useful
property: **when the writing end is closed, the reader receives "end of file"** (EOF). If a process
dies, the operating system closes all its pipes, and whoever was reading from them finds out.

Python's `multiprocessing` library creates processes, and pipes between them through which Python
objects such as dictionaries can be sent directly.

### 7.4 Signals

**Signals** are notifications the operating system delivers to a process:

| Signal | How it is produced | Can the process react? |
| --- | --- | --- |
| **SIGINT** | Pressing Ctrl+C | Yes: it can clean up before exiting, or ignore it |
| **SIGTERM** | A normal request to terminate (`kill`) | Yes |
| **SIGKILL** | `kill -9` | **No**: the process disappears instantly |

With `kill -9`, no `finally` block or cleanup function runs. The only guarantee is that the
operating system closes the process's files and pipes.

### 7.5 Asynchronous programming

**Asynchronous programming** (in Python, `asyncio`) lets a program wait on several input/output
operations at once without using several threads. It requires special functions (`async def`)
called from an **event loop**. Some libraries, such as the official MCP SDK, only offer
asynchronous functions.

## 8. Docker essentials

### 8.1 Image and container

- An **image** is a file-system template with programs already installed, for example "Python
  3.10" or "the sympy repository with its dependencies".
- A **container** is an isolated run of an image: it has its own files, processes and network,
  and does not see the host computer's unless allowed.

Containers are managed by a separate service, the **Docker daemon**. That is why **they are not
child processes of the program that created them**: if that program dies, the container stays
alive.

### 8.2 Basic commands

| Command | What it does |
| --- | --- |
| `docker pull <image>` | Downloads an image |
| `docker run <image> <command>` | Creates and starts a container running that command |
| `docker exec <container> <command>` | Runs a command inside a running container |
| `docker ps` | Lists containers (with `-a`, stopped ones too) |
| `docker rm -f <container>` | Stops and removes a container |

`docker run` options used in this project:

- `--rm`: removes the container automatically when its main process ends.
- `--network none`: no network.
- `--memory`: a memory limit. (`--cpus`, the CPU limit, is not used: some Docker installations
  reject it, section 30.2.)
- `--name` and `--label`: a name and a label, to find it later.
- `-i`: keeps the container's standard input connected.
- `--pull never`: fail instead of downloading the image if it is missing.

### 8.3 Orphaned containers

A container lives as long as its **main process** keeps running. If the program that created it
dies without removing it, it becomes **orphaned**: it keeps using resources and nobody will delete
it. Avoiding this when the program is killed with `kill -9` requires the container to depend on
something the operating system closes by itself (sections 7.3 and 23).

## 9. What MBPP is

**MBPP** (*Mostly Basic Python Problems*) is a set of about a thousand entry-level Python
programming exercises, published by Google Research. Each exercise has:

- a natural-language **description** ("write a function that…");
- the **signature** of the function to write;
- a reference solution;
- some **assertions** (`assert`) that check the result.

A solution is correct if the function passes the assertions. It is used to measure whether a model
can write small, correct functions.

When evaluating an agent it is common to **hide one of the assertions**: the agent tests its code
against the visible ones, and the final check uses all of them. This catches solutions that only
fit the known cases.

## 10. What SWE-bench is

### 10.1 The task set

**SWE-bench** is a set of tasks built from **real GitHub issues** in well-known Python projects such
as django, sympy, scikit-learn or xarray. Each task corresponds to an issue that was solved with a
code change. **SWE-bench Verified** is a subset of 500 tasks reviewed by people to make sure the
issue text is enough to solve them.

### 10.2 What the agent receives and delivers

- It **receives** the issue text and the repository in its state before the fix.
- It **delivers** a **patch**: a description of the changes made to the files.

A patch is produced with `git diff`, which compares modified files with their committed version and
shows the added and removed lines. Each modified file starts with a `diff --git` line.

### 10.3 How it is judged

The patch is applied to a clean copy of the repository and two groups of tests are run:

- those that **failed** before and must now **pass** (they show the issue is fixed);
- those that **already passed** and must **keep passing** (they show nothing else broke).

The agent does not receive the original fix. It can run the task's **evaluation script** to see how
the tests are doing.

### 10.4 Containers and `/testbed`

Installing each project with the exact versions of its dependencies would be very costly. That is
why SWE-bench distributes **one Docker image per task**, with the repository already prepared. In
those images the repository is always in the **`/testbed`** directory, which is also the default
working directory. It is not a choice made by whoever builds the agent: it is the convention of the
SWE-bench images, and the agent's tools use that path.

## 11. How an agent is evaluated

### 11.1 Metrics

Solving the task is not enough to compare agents or models. The following are also measured:

- **Success**: whether the solution passes validation.
- **Iterations**: how many turns of the loop were needed.
- **Requests**: how many API calls, retries included.
- **Input and output tokens**: the cost.
- **Time**: from start to finish.

Two agents that solve the same task are not equally good if one needs three times as many tokens.

### 11.2 Benchmarks and model comparison

A **benchmark** is a fixed set of tasks used to compare performance. Comparing models means running
the same agent, with each model, on the same tasks, and recording the metrics for each combination.
**Provider reliability** is measured too: response time, retries and availability.

### 11.3 Intermediate metrics

A failed task may have been close to being solved. **Intermediate metrics** measure progress within
a run, for example: at which iteration the agent first read the file it ended up fixing, or how many
iterations passed between the tests starting to pass and the submission.

### 11.4 Ablation

An **ablation** is an experiment that changes **a single thing** (a sentence of the prompt, a tool, a
parameter) and measures the result before and after, with the same model and the same tasks. It is
how you know whether a change improves the agent or whether the difference is due to the model's
randomness.

---

# Part II. Inside Agent Smith

This part describes what the project asks for and how Agent Smith solves it, without going into the
code.

## 12. What the subject asks for

### 12.1 The project in one paragraph

Agent Smith is an agent that solves programming tasks autonomously with the Thought → Code →
Observation loop. A language model, accessed through an API, writes Python code. That code runs in
a custom sandbox that can call tools from an MCP server, and the result goes back to the model.
The agent is applied to two benchmarks, MBPP and SWE-bench, and must respect strict limits on
iterations, tokens and time, recording real metrics for every step.

### 12.2 General requirements

1. **Python 3.10** and **uv** as the package manager.
2. **All errors handled gracefully**: an unexpected crash counts as a failure.
3. **Your own** Thought → Code → Observation **loop**, **without agent frameworks** (section 2).
4. **Code extraction** from the model's responses. It should accept formats other than a Python
   block and convert them into equivalent Python calls (section 21).
5. **A designed system prompt**: tool documentation, examples of the response format and examples
   of reasoning.
6. **All execution inside a configurable sandbox** (section 12.3).
7. **Explicit observations** in these cases: no valid code block was found; a malformed block was
   interpreted anyway (explaining how); execution hit the time limit and output is partial; output
   was truncated because of its size; an edit introduced a syntax error. The model must never have
   to guess what happened.
8. **Several providers and models**, interchangeable without rewriting the code.
9. **Free plans only**, with **several keys per provider** and **rotation** when limits are
   reached. Keys are read from environment variables or a `.env` file; a key written in the code is
   a security failure.
10. **Usage tracking**: tokens, retries, latency and requests.
11. **Tools independent of the loop**: they must be testable on their own.
12. **Only your own MCP servers.**
13. **Honesty**: the agent must not look up the solution in pull requests, issues or other external
    sources, nor bypass the sandbox. This is strictly forbidden.
14. **A `README.md`** in English with a fixed first line and sections on architecture, the loop,
    the sandbox, the tools and the results.
15. **A `BENCHMARK_REPORT.md` report** (section 12.7).

### 12.3 Sandbox requirements

**Configuration.** Sandbox limits are defined in a JSON file and loaded into a **`SandboxConfig`**
class, which the subject provides. It is a **Pydantic** model, a library that validates data and
converts it to and from JSON. Its fields are:

| Field | What it controls | Default value |
| --- | --- | --- |
| `authorized_imports` | Modules that may be imported; `math.*` also allows its submodules | `math`, `collections`, `itertools`, `re`, `json`, `typing`, `functools`, `random`… |
| `allowed_directories` | Folders where reading and writing are allowed | `/testbed` and `/tmp/agent` |
| `max_execution_time_seconds` | Maximum time for one code block | 30 |
| `max_memory_mb` | Maximum memory | 512 |

**What it must block:** imports outside the list, file access outside the allowed directories, the
network, blocks that exceed the time limit, excess memory and dangerous builtins. All of this
**with the standard library only**: external packages such as RestrictedPython are forbidden.

**`final_answer`.** A function the sandbox itself makes available to the code. When the code calls
it with a string, the sandbox captures that string and tells the loop the task is finished. **It is
not an MCP tool**: it is always present, whatever server is connected. For MBPP it receives the
solution code; for SWE-bench, the patch returned by `get_patch()`.

**Two kinds of functions.** Inside the sandbox the code sees the functions that wrap the tools
discovered on the MCP server, which change with the server, and `final_answer`, which does not.

**MCP integration.** stdio and streamable HTTP transports; tools, resources and prompts exposed;
tools callable as Python functions; working with an unknown server; and a **generated manual**
built from the schemas and included in the prompt.

**A command-line command**, `uv run sandbox`, with an interactive mode (section 14).

**Exception propagation.** `KeyboardInterrupt` and `SystemExit` must not be silently swallowed.

### 12.4 MBPP requirements

- **Input**: a JSON file with the identifier, the description, the function signature, the imports
  the tests need and the list of public assertions (model `MBPPTaskInput`).
- **Required tool**: `run_tests`, on your own MCP server.
- **Output**: the result JSON (section 12.6), with the function code as the solution.
- **Command**: `uv run python -m agent_mbpp --task-file … --output … --model-name … --provider-url …`
- **Per-task limits**: 10 iterations, 6,000 input tokens, 1,500 output tokens and 120 seconds.
- **A configurable maximum number of iterations.**

### 12.5 SWE-bench requirements

- **Input**: a JSON file with the identifier, the issue text, the Docker image, the evaluation
  script, optional hints and the repository name (model `SWEBenchTaskInput`).
- **Container**: the agent starts the task image and is **responsible for removing the container**
  when it finishes.
- **Where the sandbox goes**: inside the container, or on the host with MCP tools that reach into
  the container. Both options are valid.
- **Nine required tools**, with these signatures:

| Group | Tool | What it does |
| --- | --- | --- |
| Files | `read_file(filepath, start_line, end_line)` | Reads a range of numbered lines |
| Files | `edit_file(filepath, old_str, new_str)` | Replaces an exact string with another |
| Files | `list_files(directory, pattern)` | Lists files matching a pattern |
| Search | `search_code(pattern, file_pattern)` | Searches like `grep`: `path:line content` |
| Search | `search_function_or_class_definition_in_code(name)` | Finds the definition of a function or class |
| Search | `find_references(name, filepath, line)` | Finds the uses of a name |
| Execution | `run_tests()` | Runs the evaluation script |
| Execution | `get_patch()` | Returns the `git diff` of the changes |
| Execution | `run_command(command, workdir)` | Runs a command and returns output, errors and exit code |

- **Output**: the result JSON, with the patch as the solution, generated with
  `git -c core.fileMode=false diff`.
- **Command**: `uv run python -m agent_swebench` with the same arguments as MBPP.
- **Per-task limits**: 30 iterations, 300,000 input tokens, 10,000 output tokens and 900 seconds.

Token limits are **cumulative** over the whole task, and reasoning tokens count like any others.

### 12.6 The result JSON

Each run of the agent writes a `solution.json` file with the **`SolutionOutput`** structure. Its
**`steps`** field is a list with one **`StepMetrics`** element per iteration.

**`StepMetrics`: what is recorded for each iteration**

| Field | Content |
| --- | --- |
| `step` | Iteration number, starting at 1 |
| `input_tokens`, `output_tokens` | Measured tokens for that iteration |
| `request_time_ms` | Time of the API call, in milliseconds |
| `api_url`, `model_name` | Provider and model used in that step |
| `llm_output` | The model's response, unmodified |
| `sandbox_input` | The code sent to the sandbox |
| `sandbox_output` | What the execution returned: the observation |
| `retries` | Retries needed in that iteration (0 if the first request worked) |
| `timestamp` | When it was recorded, in ISO 8601 format |

**`SolutionOutput`: the task result**

| Field | Content |
| --- | --- |
| `task_id`, `benchmark` | Which task, from which benchmark (`mbpp` or `swebench`) |
| `success` | Whether the agent **believes** it solved the task; validation decides for real |
| `solution` | The function code (MBPP) or the patch (SWE-bench) |
| `system_prompt` | The full system prompt that was sent |
| `iterations` | How many iterations were used: the number of elements in `steps` |
| `total_requests` | How many API requests were made, **retries included** |
| `total_input_tokens`, `total_output_tokens` | The sum of the tokens over all steps |
| `total_time_seconds` | Wall-clock time from the agent's start to the end |
| `steps` | The list of `StepMetrics` |
| `error` | The reason for failure, or empty if there was none |
| `timestamp` | When it was written |

So `iterations` and `total_requests` do not have to match: an iteration with two retries adds 1 to
`iterations` and 3 to `total_requests`.

These fields exist so that **the agent's reasoning can be traced** and the figures shown to come
from a real run. Totals are the sum of the steps, and every token count comes from what the
provider reported, never from an estimate or an invented value.

### 12.7 The benchmark report

`BENCHMARK_REPORT.md`, at the root of the repository, compares **at least 5 models on the same 3 or
more SWE-bench tasks**, and includes:

1. **Setup**: models, providers, tasks and why they were chosen.
2. **Results table** per model and task: pass or fail, iterations, input and output tokens, and
   time.
3. **Provider reliability**: average response time, retries and availability.
4. **At least two intermediate metrics** (section 11.3).
5. **At least one ablation** (section 11.4).
6. **Data-based conclusions**: which models are chosen and which are discarded.

The `solution.json` files backing the report must be in the repository.

## 13. The working environment

| Piece | What it is |
| --- | --- |
| **The project repository** | Your code: the agent, the sandbox, the MCP servers and the configuration |
| **The moulinette** | A program provided with the subject that produces tasks and validates solutions. **It never runs your code** |

The moulinette has three commands:

- **`dump`**: writes a task to a JSON file. For MBPP it **hides the first assertion**: the agent
  only sees the others.
- **`validate`**: takes the task and the `solution.json` and checks two things. **Correctness** (for
  MBPP it runs every assertion, including the hidden one; for SWE-bench it applies the patch and
  runs the tests) and **metrics** (iterations, input tokens, output tokens and time within the
  limits). Only the final `PASSED` result means the task is solved.
- **`display`**: shows a `solution.json` in a readable way, which is handy for inspecting the steps.

## 14. The three commands

Agent Smith has three commands. The two agent commands use an AI model; the sandbox one does not.

### 14.1 Summary

| Command | What it is for | Needs | Produces |
| --- | --- | --- | --- |
| `uv run sandbox` | Running Python in the sandbox, with or without an MCP server | Nothing mandatory | Whatever the code prints |
| `uv run python -m agent_mbpp` | Solving an MBPP task with a model | Task, model, URL, keys, Docker | `solution.json` with the code |
| `uv run python -m agent_swebench` | Solving a SWE-bench task with a model | Task, model, URL, keys, Docker | `solution.json` with the patch |

### 14.2 `uv run sandbox`

This is the sandbox without the agent: it works for any Python code that respects its restrictions.
The subject requires it so the sandbox and the tools can be tested independently.

```bash
uv run sandbox                                             # interactive, default configuration
uv run sandbox config.json                                 # with a custom configuration
uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py"      # with the MBPP tools
uv run sandbox --mcp-stdio "python mcp_tools_swebench.py"  # with the SWE-bench tools
uv run sandbox --mcp-server http://127.0.0.1:8000/mcp      # with an already running server
```

- **Configuration**: optional. Without a file, the `SandboxConfig` defaults are used.
- **MCP server**: optional, and only one: `--mcp-stdio` with the command that starts it, or
  `--mcp-server` with its URL. If one is connected, the manual is printed.
- **Two input modes**, depending on where the input comes from:
  - **Interactive**, when typing in a terminal: it shows `>>>`, runs each entry and asks for
    another. A multi-line block is closed with an empty line, as in the Python interpreter. It ends
    with `exit` or Ctrl+D.
  - **Script**, when the input comes through a pipe (`cat test.py | uv run sandbox`): it reads the
    whole text and runs its statements one by one.
- **Persistent variables**: whatever one entry defines is still available in the next ones.
- If a block runs out of time, the process that runs the code is replaced by a new one, with a
  warning that **the variables have been lost**.

**Processes:**

| Process | When it exists | What it does |
| --- | --- | --- |
| The `sandbox` command | Always | Reads input, prints results, is the MCP client |
| Worker | Always | Runs the code under the restrictions |
| MCP server | Only with `--mcp-stdio` | Started by the command as a child process |
| Docker containers | If the tools use them | Created by the MCP server |

With `--mcp-server`, the server is already running elsewhere and the command only connects to it.

### 14.3 `uv run python -m agent_mbpp`

```bash
uv run python -m agent_mbpp --task-file task.json --output solution.json \
  --model-name <model> --provider-url <url>
```

Optional argument: `--max-iterations`, 10 by default and never above that limit.

**Processes:** the **agent**, which holds the keys and runs everything; the **worker**, which runs
the model's code; the **MBPP MCP server**, started by the agent over stdio; and a short-lived
**Docker container** every time the model calls `run_tests`.

### 14.4 `uv run python -m agent_swebench`

```bash
uv run python -m agent_swebench --task-file task.json --output solution.json \
  --model-name <model> --provider-url <url>
```

Optional argument: `--max-iterations`, 30 by default and with that maximum.

**Processes:** the **agent**; the **task container**, a single one for the whole task, held by the
`docker run` command the agent launches (section 23.3); the **SWE-bench MCP server**, which works
inside that container; and the **worker**.

### 14.5 Why the agent only works for those two benchmarks

The loop is shared, but each benchmark needs its own pieces, which we call an **adapter**: its
system prompt, how it presents the task, its limits, its MCP server and how it prepares its
environment (setting up the tests for MBPP, starting the container for SWE-bench). Another kind of
task would need a new adapter; the loop, the sandbox and the provider client would be reused as
they are.

## 15. Architecture: three processes

### 15.1 Overview

A task of the agent runs in three Python processes, plus the Docker containers:

```
AGENT (main process)
├── holds: API keys, limits, task clock, provider client, MCP client
│
├── WORKER (child process)                   ← runs the model's code
│     no keys, no Docker, no network, limited imports, files and memory
│
└── MCP SERVER (child process, over stdio)   ← runs the tools
      └── Docker: tests, reading and editing the repository
```

### 15.2 The agent

The process started by the command. It loads the task, creates the provider client, starts the MCP
server and the worker, runs the loop and, at the end, closes everything in order and writes the
result. Of the three, it is **the only process that knows the API keys**.

Its code is **synchronous**: it does not use `asyncio`. The only exception is inside the MCP client,
because the official MCP SDK only offers asynchronous functions. The client starts a **thread** with
its own event loop and sends every operation there; for the rest of the agent, calling MCP is an
ordinary function that waits for the answer.

### 15.3 The worker

The process where **the code written by the model runs**. The agent starts it at the beginning of
the task and it lives until the end. That way it runs every block in the **same namespace**, and
variables persist between iterations.

When it starts, before accepting any code:

1. It **clears its environment variables** (it only keeps the logging ones). The model's code cannot
   read the keys.
2. It **ignores Ctrl+C**: the agent handles that signal and then closes it.
3. It moves into its own **temporary directory**.
4. It applies the **memory limit** and **disables the network**.
5. It prepares the namespace: restricted builtins, `final_answer` and one function per discovered
   MCP tool.
6. It tells the agent it is **ready**.

It is started in **spawn** mode: a fresh Python interpreter that does not inherit the agent's memory
(neither the provider client nor the MCP thread).

**Why it is a separate process.** If a block never finishes, the agent **kills the process**. With a
thread that would not be possible (section 6.3). A separate process also shares no memory with the
agent and cannot read its variables.

### 15.4 The MCP server

The process that **does the trusted work**: running tests in Docker, reading and editing the
repository. The agent starts it over stdio with a **minimal, explicit environment**: the program
path, the Docker variables, the task deadline and the data it needs (the session label for MBPP; the
container and the evaluation script for SWE-bench). It does not inherit the keys.

**Why it is a separate process.** The subject requires it, and it also separates responsibilities:
the model's code, with no permissions, asks for operations; the server, with Docker access, only
runs the tools it advertises.

### 15.5 What each process can see

| | API keys | Docker | Network | MCP session |
| --- | --- | --- | --- | --- |
| Agent | Yes | Yes (SWE-bench) | Yes (model API) | Yes |
| Worker | **No** | **No** | **No** | **No**: it only asks for operations |
| MCP server | **No** | Yes | Containers have no network | It is the other end |

## 16. How the processes communicate

### 16.1 Three channels

| Between | Channel | Format |
| --- | --- | --- |
| Agent ↔ worker | `multiprocessing` pipe | Python dictionaries |
| Agent ↔ MCP server | The server's standard input and output (stdio) or HTTP | MCP protocol (JSON-RPC) |
| MCP server ↔ Docker | `docker` commands run as processes | The text output of each command |

Since the MCP server's standard output carries the protocol, **log messages always go to standard
error**. A stray `print` in the server would break the communication.

### 16.2 Messages between agent and worker

| Message | Direction | Meaning |
| --- | --- | --- |
| `ready` | worker → agent | Set up and waiting for code |
| `execute` | agent → worker | Run this block |
| `output` | worker → agent | Text printed by the code, sent as soon as it is printed |
| `mcp_request` | worker → agent | The code called a tool |
| `mcp_result` | agent → worker | Result (or error) of that tool |
| `done` | worker → agent | Block finished, with its final answer or its error |

The conversation is **strictly sequential**: there is only one operation in progress at a time.
There is no need to number messages or handle concurrency.

The agent waits for each message **with a time limit**. If it does not arrive in time, the block has
exceeded its limit: the agent kills the worker. If the worker dies by itself, for example because it
ran out of memory, the agent receives "end of file" through the pipe and knows immediately.

Sending output **as soon as it is printed** has a reason: if the block is interrupted by the time
limit, the agent already has what was printed and can give the model partial output.

### 16.3 The journey of a tool call

When the model's code runs `print(run_tests(code=solution, test_list=test_list))`:

```
 WORKER                   AGENT                      MCP SERVER            DOCKER
     │                       │                            │                  │
 run_tests(...)              │                            │                  │
     │── mcp_request ───────▶│                            │                  │
     │                       │ pauses the block clock     │                  │
     │    (waiting)          │── MCP call (stdio) ───────▶│                  │
     │                       │                            │── docker run ───▶│
     │                       │                            │◀── result ───────│
     │                       │◀── MCP result ─────────────│                  │
     │◀── mcp_result ────────│ resumes the clock          │                  │
 print(result)               │                            │                  │
     │── output ────────────▶│                            │                  │
     │── done ──────────────▶│                            │                  │
```

Three ideas from this diagram:

1. **The `run_tests` function the model sees is a wrapper.** It runs nothing: it packs the arguments,
   asks the agent for the operation and waits. The worker never talks to the MCP server.
2. **The agent is the intermediary.** This way the model's code cannot use the MCP session for
   anything other than calling an advertised tool.
3. **Waiting time is not charged to the block**, but it is charged to the task (section 22.3).

### 16.4 Errors in a tool call

Not all errors are alike:

- **The model called it wrongly** (non-existent tool, code -32601; invalid parameters, code -32602)
  or **the tool reported an error of its own**: the error is returned to the code as an ordinary
  exception. If the code does not catch it, it appears in the observation and the model can
  correct itself.
- **The connection to the server broke** or timed out: the task cannot continue and ends with a
  recorded error.

## 17. An MBPP task step by step

1. **The clock starts first.** The command records the start time before even reading the task:
   the 120-second limit includes setup.
2. **The task is read and validated** with its Pydantic model.
3. **The deadline is computed with a cleanup reserve**: 120 seconds minus 5, kept to close the
   worker, the server and the containers without exceeding the limit.
4. **The provider client is created**: it looks up the models configuration entry matching the
   requested model and URL, and reads its keys from the environment (section 24).
5. **The MBPP MCP server is started** with its minimal environment, which includes a random
   **session label** used to tag its containers.
6. **Its capabilities are discovered** and the manual is generated. If the server does not advertise
   `run_tests`, the task stops here with an error.
7. **The system prompt is built**: instructions, an example of the Thought → Code → `<end_code>`
   format, how to use `run_tests` and `final_answer`, and the manual.
8. **The worker is started** with the sandbox configuration and the list of tools.
9. **The data is prepared**: a first block defines `test_imports` and `test_list` in the worker, so
   the model can use them without copying them.
10. **The loop runs** (section 19). The model writes the function, tests it with `run_tests` and,
    once it passes, calls `final_answer` with the code.
11. **Everything is closed**, whatever happens: worker, MCP server and, finally, any container still
    carrying the session label.
12. **`solution.json` is written**, also when the task failed, with the metrics that were actually
    measured. If cleanup fails or the total time exceeds the limit, the result is marked as failed.

The command's exit code is 0 when the result has been written. **It does not mean the task is
solved**: `success` says that and, ultimately, the moulinette.

## 18. What changes for SWE-bench

The skeleton is the same. This changes:

- **Limits**: 30 iterations, 300,000 and 10,000 tokens, 900 seconds, with a **20-second** cleanup
  reserve, because removing a large container takes longer.
- **Before the MCP server, the task container is started**: if the image is missing it is
  downloaded; then the container is launched without a network and checked for `/testbed`
  (section 23.2).
- **The MCP server receives the container identifier** and the evaluation script. All its tools
  work inside that container.
- **The server must advertise all nine tools** before starting.
- **The prompt describes a method**: locate the code, read it before changing it, make the minimal
  change, run the tests, and submit `final_answer(get_patch())` only when `get_patch` shows changes.
  It also reminds the model that sandbox code cannot import the project (`run_command` exists for
  running it) and that it must not look for the official fix.
- **The task message** presents the identifier, the repository, the issue text and the hints, if
  any.
- **Final check**: even if the model calls `final_answer`, the task only counts as successful if the
  answer contains `diff --git`. A model may submit the "No changes yet." notice that `get_patch`
  returns when there are no changes, and that is not a patch.

## 19. The loop in detail

The loop is **the same for MBPP and SWE-bench**. The adapter gives it the system prompt, the task
text, the limits, the provider client and the already started sandbox.

### 19.1 One iteration, step by step

1. **Checks before spending.** If the deadline has been reached or the tokens are exhausted, the loop
   ends without making any request.
2. **Select the history** to send (section 19.4).
3. **Ask the provider for a response.** The client may make several attempts (section 24) and returns
   the text, the measured tokens, the number of requests and a possible error.
4. **Add up the counters.** If no request was made at all, the task ends.
5. **Record the step immediately**, before knowing whether it went well. That way a failed iteration
   appears in the result with its real consumption.
6. **Assess the error, if any** (section 19.3).
7. **Extract the code** from the response (section 21).
8. **Run it** in the sandbox, if there is code. If not, the observation explains why nothing was run
   and asks for a complete block.
9. **Build the observation**: extraction notice, printed output, error, timeout notice and final
   answer, whichever apply. If the block printed nothing, the observation says so explicitly,
   because an empty observation confuses the model.
10. **Append to the history** the model's response and the observation.
11. **Decide whether to stop**: on a final answer, a worker failure or the deadline.

### 19.2 How it ends

| Exit | When | Result |
| --- | --- | --- |
| **Valid final answer** | The block called `final_answer` with non-empty text, with no error and no timeout | `success` true |
| **Invalid final answer** | Empty, or the block ended with an error or a timeout | `success` false, with the reason |
| **Limit** | Deadline, tokens or iterations exhausted | `success` false: "Iteration limit reached without final_answer", etc. |
| **Provider failure** | Non-recoverable error (section 19.3) | `success` false |
| **Worker failure** | Block time exhausted or process died | `success` false: its state is lost |
| **Unexpected error** | Any exception from the loop itself | Recorded; earlier steps are kept |

In every case a complete result is returned. The loop never lets exceptions escape.

### 19.3 Recoverable and fatal errors

When the provider returns an error, the loop distinguishes two cases:

- **Recoverable**: the model **did** respond (status 200) and its usage is measured, but the response
  contains no usable text. It is returned to the model as an observation and the loop continues.
  Losing the whole task over an occasional empty response would be disproportionate.
- **Fatal**: the provider rejected the request and the attempts ran out, usage is unknown, a limit
  was exceeded or the deadline passed. The step is recorded with the error and the task ends.

### 19.4 What the model remembers

The full history is **not** always sent. Each request carries:

- the system prompt and the task text, always;
- the **most recent messages** that fit in a **budget**, and never fewer than six.

The budget is recomputed at every iteration: **the remaining input tokens divided by the remaining
iterations**. If the first turns spend little, later ones get more room; if a huge observation uses
a lot, the window shrinks by itself.

A model's configuration can also set a **maximum input per request**. When it does, the budget never
exceeds it. Only one model uses it: its free plan refuses any request above 7,000 input tokens, so
its requests are kept to about 6,000 (section 26.3).

There are two reasons not to use a simpler alternative:

- **Sending everything** makes the cost grow very quickly, because every observation is resent in
  every later request (section 3.3). In SWE-bench it came close to using the whole input budget of a
  task.
- **A small fixed window** makes the model forget what it already did: in one test it kept rereading
  the same lines of a file it had already edited.

This trimming only affects what is sent. **The `solution.json` keeps every step in full.**

## 20. Design decisions

The subject states what must exist but leaves most of the how open. These are the main decisions.

| Decision | Rejected alternative | Reason |
| --- | --- | --- |
| **Own loop**, shared by both benchmarks, with one adapter per benchmark | An agent framework; one loop per benchmark | Required by the subject; a single loop is explained and changed in one place |
| **Worker in a separate**, persistent **process** | Running in a thread of the agent | A thread cannot be killed if it never finishes; a process can, and it does not see the keys |
| **Synchronous agent**; the asynchronous part stays inside the MCP client | The whole agent asynchronous | Only the MCP SDK requires it; the rest reads as ordinary code |
| **`multiprocessing` pipe with dictionaries** | A custom JSON message protocol | Less code: the library serialises and detects closure |
| **Sandbox on the host**, tools that reach into the container | Sandbox inside the container | The subject allows both; this way the worker never has Docker access |
| **OpenAI's official SDK** for every provider, with its retries disabled | Hand-written HTTP requests | Less code to explain; disabling its retries lets every request be counted |
| **Explicit selection** of the model by URL and name | Switching providers automatically after a failure | Each result belongs to a known model and is reproducible |
| **Known versus unknown usage** (section 24.4) | Recording zero when `usage` is missing | The subject forbids inventing metrics |
| **The `docker` command for both benchmarks** | Docker's Python library | A single mechanism and one dependency fewer |
| **SWE-bench container held by the agent's standard input** | Keeping it alive with a command that never ends | It is the only way for it to disappear even if the agent is killed with `kill -9` (section 23.3) |
| **Tolerant extraction**: translating the call formats models use | Forbidding them in the prompt | Hardening the prompt does not remove them; translating them recovers lost iterations |
| **With several blocks, the first one that calls a tool** | The first block; the last block; every block | Measured on 1,502 saved replies (section 29.1) |
| **History limited by budget** | Full history; a fixed window | Section 19.4 |
| **A per-request input cap only for the model that needs it** | The same cap for every model | A cap for all would change runs that already pass (section 26.3) |
| **Bounded tool outputs**, except the patch | Returning them in full | Every observation is resent many times; the patch is the deliverable and is not cut |
| **`edit_file` rejects** ambiguous, no-op or non-compiling edits | Applying the first match and always confirming | Confirming a change that does not exist makes the model repeat the same edit |
| **Echo of the block's last expression**, like the Python interpreter | Showing only what is printed with `print` | Models call tools without `print` and got empty observations |

## 21. Extracting code from the response

### 21.1 The requested format

The prompt asks for a short thought, **one closed Python block** (opened with three backticks and
`python`, closed with three backticks) and the `<end_code>` marker. That marker is also a stop
sequence: the provider cuts the response there, and the model never gets to invent the observation.

The code is extracted from the block and its syntax is checked **before** running it.

**When a reply contains several closed blocks**, only one runs. It is **the first block that calls a
tool or `final_answer` and compiles**. The tool names are the ones discovered on the MCP server, so
nothing is written by hand. If no block calls a tool, the first block runs.

The reason is that models often write an **example** before the real action: the definition of the
function they are about to fix, an `if` they plan to insert, an `import`. Running the first block ran
that example, and the model received an observation about code it never meant to execute. The other
obvious rules are worse: the last block often is `final_answer(get_patch())` written right after
the action, so it would submit before seeing the result; and running every block executes the
examples too. Section 29.1 tells how this was found and measured.

### 21.2 What happens when the format is not followed

| Situation | What is done | What the model receives |
| --- | --- | --- |
| Empty response | Nothing runs | "Model response was empty" |
| No Python block | A call translation is attempted (section 21.3) | If there is nothing to translate, that no code was found |
| Unclosed block | **Not run** | That the closing fence is missing |
| Syntax error | Not run | The line and the reason |
| The thought is inside the block and a second block is inside it | The second block runs | Its result |

An unclosed block is not run because it may be truncated: running half an edit is worse than
running nothing.

### 21.3 Call formats that are translated

Many models, especially after seeing a tool result, stop writing the Python block and use the call
format they were trained on. Agent Smith translates two of them into an equivalent Python line,
always of the form `print(tool(argument=value))`:

- **`<tool_call>` with `<arg_key>` and `<arg_value>` pairs.** The value markers are treated as
  optional, because with long values models forget one of the two.
- **`<tool_use>` with `<tool_name>` and JSON arguments.**

There is a third case: some providers return a **native call** through the API's function channel,
with no text. The provider client converts it to the `<tool_use>` format, so there is only one place
where a call becomes Python.

Two translation rules:

- **Always with `print`**: without it, the result would not appear in the observation.
- **Values are written as Python literals**, never as code. A value with quotes or line breaks
  becomes an inert string, so it cannot inject statements.

When the code comes from a translation, the observation says so. The subject requires a notice
when a malformed block is interpreted anyway.

### 21.4 Formats that are not translated

The XML `<invoke>` format and the ReAct format (`Action:` / `Action Input:`), which the subject gives
as examples, are not implemented because none of the models used has produced them. If one appeared,
another translation would be added next to the existing ones.

## 22. Sandbox controls

### 22.1 The controls, one by one

| Control | How it is applied |
| --- | --- |
| **Imports** | A custom importer checks `authorized_imports`. It accepts patterns such as `collections.*`, rejects relative imports and `import *`, and also checks submodules requested with `from … import …` |
| **Builtins** | An **explicit list** of allowed builtins is built. `eval`, `exec` and `compile` are not in it. `__import__` and `open` are replaced with controlled versions |
| **Files** | `open` resolves the full path (following `..` and links) and checks that it **belongs** to an allowed directory. An empty list allows nothing |
| **Network** | `socket` is not in the import list. On top of that, its connection functions are replaced with one that raises an error, in case an allowed library tried to use them |
| **Memory** | An operating-system limit on the worker's memory space, applied before it accepts code |
| **Time** | Applied by the agent from outside: if the block does not finish in time, it kills the worker |
| **Environment** | The worker clears its environment variables and runs in a temporary directory |

The import and builtin restrictions apply **only to the namespace of the model's code**. The rest of
the worker runs normal Python.

### 22.2 Output is limited too

A block's output is kept up to **12,000 characters**, with a notice saying how many were omitted.
Without that cap, a `print` inside a loop would fill the observation, which is then resent with every
request. **The final answer is never cut.**

### 22.3 Two clocks

Two deadlines run at once during a block, and whichever runs out first wins:

- **The block clock**: `max_execution_time_seconds`. It **does not count time spent waiting for MCP
  tools**, because that time is spent by a trusted tool, not by the model's code. The subject says so
  explicitly: the sandbox timeout only applies to code running inside it.
- **The task deadline**: 120 or 900 seconds minus the cleanup reserve. **It discounts nothing**,
  because the moulinette measures real time.

If `run_tests` takes twenty seconds in Docker, the block is not penalised, but the task does spend
those twenty seconds.

When a deadline runs out during a block, the agent kills the worker. In the `sandbox` command a new
one is started with a warning that variables were lost; in the agent, the task ends with the error
recorded.

### 22.4 Exceptions from generated code

If the model's code raises `SystemExit` or `KeyboardInterrupt`, it is treated as that block's error:
the model is told in the observation and the worker keeps running. They are not silently swallowed.
A real Ctrl+C from the user reaches the agent, which closes the worker and the other resources.

`final_answer` works by raising its own exception carrying the answer. The worker recognises it
before any other error, stops the block and sends the answer to the agent.

### 22.5 What these controls do not protect against

- The memory limit applies to the **virtual address space**, which is not exactly the physical memory
  used.
- Restricting imports and `open` does not control everything an allowed library might do.
- There is no defence against **hostile Python introspection** (section 6.4).
- The boundary is a **process**, not a container or an operating-system mechanism.

These are known and accepted limits: the subject requires the standard library only, and these
controls cover what it asks for.

## 23. Docker in Agent Smith

Docker is used in two different ways.

| | MBPP | SWE-bench |
| --- | --- | --- |
| Image | Clean Python (`python:3.11-slim`), the same one the moulinette validates with | The task's, with the repository in `/testbed` |
| How many containers | **One per `run_tests` call** | **One per task** |
| Who creates it | The MCP server | The agent |
| How long it lives | Seconds | The whole task |
| How it is cleaned up | `--rm` and a sweep by label | It stops when its standard input is closed |

### 23.1 MBPP: one container per test run

`run_tests` combines the test imports, the candidate code and the assertions into one program, and
runs it in a new container:

- **without network** and with **128 MB** of memory, with no CPU limit (section 30.2);
- with **`--rm`**, so it disappears when done;
- with a **label** identifying the task's session;
- with **`--pull never`**: the image must already be available. If it is missing, `run_tests`
  reports a Docker error instead of downloading it during the task (section 30.3).

The image is the one the moulinette uses to validate MBPP solutions. Using the same one means a
solution that passes here was tested on the interpreter that will judge it, and only one image has
to be downloaded in advance.

The time limit is 10 seconds, or less if the task deadline is near. If it runs out, the container is
removed explicitly, because stopping the `docker` command does not stop the container.

The result states whether the tests passed, a message, the output (limited to 12,000 characters) and
the exit code. Exit code **125** is treated as a failure of Docker itself, for example a missing
image, not as a test failure.

When the task ends, **after closing the MCP server**, the agent removes any container still carrying
its session label. The order matters: if the server had died, it could no longer delete its own
containers.

### 23.2 SWE-bench: one container per task

The agent checks whether the task image exists, downloads it if needed and starts a container
**without network** and with a unique name. It waits until it is running and checks that it contains
`/testbed`.

The MCP server's tools run each operation with `docker exec` inside that container. Some details:

- **Paths are always expressed as `/testbed/...`**. A path that leaves the repository is rejected.
- **The model's arguments travel as separate elements of the command**, never inside a string
  interpreted by the shell. That way a text with quotes or line breaks cannot turn into another
  command, and `edit_file` can replace multi-line blocks without escaping them.
- **Outputs are limited to 4,000 characters** (the beginning and the end are kept) and searches to
  **50 matches**. `get_patch` is never cut.
- **`run_tests`** runs the task's evaluation script and returns the part between its start and end
  markers, which is where the test result is.
- **`edit_file`** rejects the edit if the text does not appear exactly once (and says on which lines
  it appears if there are several), if the new text is identical to the old one, or if the resulting
  Python file does not compile.
- **`find_references`** is a text search for the name, not an analysis of the program.

The same tools can also work **without a container**, on a host folder given by an environment
variable. This is useful for testing the tools on their own, and paths still look like
`/testbed/...` to the model.

### 23.3 The `kill -9` problem

A robust agent should leave no container behind **even if it is killed with `kill -9`** while a task
is running.

No cleanup written in the agent can help: with `kill -9` nothing runs (section 7.4). And since the
container is not a child process of the agent (section 8.1), it does not die with it.

The solution is to make **the container depend on something the operating system closes by
itself**:

1. The agent runs `docker run -i --rm … <image> cat` and keeps that command's **standard input**
   open.
2. Inside the container, the main process is `cat`, which reads its input and **ends when it
   receives "end of file"**.
3. If the agent dies, **in any way**, the operating system closes its pipes.
4. `cat` receives end of file and ends, the container stops and `--rm` removes it.

A normal exit works the same way: the agent closes the pipe and, to be safe, also runs
`docker rm -f`.

The usual alternative, keeping the container alive with a command that never ends, leaves it
orphaned in exactly this case.

### 23.4 MBPP and `kill -9`

MBPP containers do not use that technique because they live for a few seconds and carry `--rm`. If
the agent is killed with `kill -9` exactly while one is running, it could remain until its program
finishes. It is a small, accepted risk given how short that window is.

## 24. The provider

### 24.1 Model selection

The project has a **models configuration file** with a list of entries. Each entry describes a
specific model from a specific provider:

- base URL and model name;
- **names of the environment variables** holding its keys (never the keys);
- maximum time per request and maximum number of retries;
- temperature and stop sequences;
- maximum output tokens **per request**;
- optionally, maximum input tokens **per request** (section 19.4);
- reasoning options, for models that support them.

The command receives the model and the URL, and the client looks for **exactly one** matching entry.
If there are zero or more than one, the task does not start. There is no automatic model switching:
each result belongs to the requested model.

The file path can be given with an environment variable; if not, the configuration file included in
the repository is used.

Through a router (section 4.4), a request with stop sequences also asks the router to use **only
providers that honour every parameter**. Without that, the request could be forwarded to a provider
that ignores `stop`, and the model would invent observations again.

### 24.2 Keys

The client reads every key variable of the entry that exists and removes duplicates. If it finds
none, the task does not start.

Keys **never appear in a message**: they are registered so the logging system replaces them with
neutral text, and the provider's error messages are cleaned before being stored, because some
providers include the key in the error.

### 24.3 The attempts of one request

Every time the loop asks for a response, the client makes **one or more attempts**, up to the
configured maximum. Before each attempt it checks:

1. **That the key is available.** Each key remembers until when it must not be used. If the wait is
   under a minute, it waits; if longer, it stops, because that means every key is exhausted and
   waiting would only burn the task's time.
2. **That there is time left.**
3. **That the request's token estimate fits in what is left.** The estimate uses the text size (about
   four bytes per token plus a margin): it is not exact, but it avoids sending a request that would
   certainly exceed the limit.
4. **How many output tokens to ask for**: the smaller of what is left for the task and the per-request
   maximum.

Then, depending on the response:

| Response | Usage | What the client does |
| --- | --- | --- |
| **429** | Known zero | Records how long to wait from `retry-after`, **switches to the key that will be available soonest** and retries |
| **500, 502, 503, 504** | Known zero | Records a short wait and retries |
| **Other 4xx** (400, 401, 404…) | Known zero | Stops: repeating would not fix it |
| **Timeout or lost connection** | **Unknown** | Stops and marks usage as incomplete |
| **200 without complete `usage`** | **Unknown** | Stops, keeps what was added up so far and says so |
| **200 that exceeds the budget** | Measured | Stops with an error |
| **200 without text** | Measured | Retries; if attempts run out, the error is recoverable (section 19.3) |
| **200 with a native call and no text** | Measured | Converts it to text (section 21.3) |
| **200 with text** | Measured | Returns the response |

The SDK's own retries are **disabled**: if the SDK retried on its own, those requests would not show
up in `total_requests`.

### 24.4 Known and unknown usage

This distinction explains almost all of the table above:

- If the provider **rejects** the request (4xx or 5xx), it generated nothing: its missing `usage` is a
  **known zero**, and retrying hides no consumption.
- If it answers **200 without `usage`**, or the response never arrives, the model may have generated
  something and **nobody knows how much**. Retrying would add unknown usage to unknown usage, so it
  stops and the result states that the totals are **known subtotals**.

One detail of ordering matters here: if a rejection were marked as unknown usage, the task would stop
before reaching key rotation, and the second key would never be used.

### 24.5 What is recorded for each iteration

- **`input_tokens` and `output_tokens`**: the measured sum of all attempts in that iteration.
- **`retries`**: the number of attempts minus one.
- **`request_time_ms`**: the summed time of the attempts.
- **`model_name`**: the model **the API says** it used, which through a router may differ from the one
  requested (section 4.4). The **requested** model is a separate piece of data, the one in the
  configuration, and it is the one sent in the request.

---

# Part III. A SWE-bench task from start to finish

Section 10 explains what SWE-bench is, and Part II describes the pieces separately. This part
follows a real task from the moment it exists as a file until the moulinette considers it solved.

## 25. SWE-bench from start to finish

### 25.1 Where tasks come from

The moulinette takes its tasks from the **SWE-bench Verified** set (section 10.1). For first tests,
the subject suggests `sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629`.

`moulinette_eval dump swebench --task-id <task>` writes a `task.json`. These are its fields for the
task `sympy__sympy-13480`:

| Field | Value |
| --- | --- |
| `instance_id` | `sympy__sympy-13480` |
| `repo` | `sympy/sympy` |
| `problem_statement` | The issue text: ".subs on coth(log(tan(x))) errors for certain integral values", with the failing code and the error it produces |
| `hints_text` | Comments from the discussion. For this task: "There is a typo on line 590: `cotm` should be `cothm`" |
| `docker_image` | `swebench/sweb.eval.x86_64.sympy_1776_sympy-13480:latest` |
| `eval_script` | A bash script that runs the tests (section 25.6) |

Agent Smith receives this file with `--task-file` and validates it with the `SWEBenchTaskInput`
model.

### 25.2 What the image contains

SWE-bench prepares one image per task. Each one contains:

- the repository in **`/testbed`**, at the commit **before** the fix: the bug is still there;
- a conda environment called **`testbed`**, with the exact Python version and dependencies that
  commit needs;
- `/testbed` as the default working directory.

In practice it is a miniature computer with the project ready to run and the bug still unfixed.

Images take up **several gigabytes**. If one is not available, Agent Smith downloads it at the start
of the task, and **that time counts within the 900 seconds**: the clock starts before the download.
That is why it is worth downloading task images in advance.

### 25.3 Two different places: the host and the container

It is important to tell apart where each thing happens:

```
HOST COMPUTER                                        TASK CONTAINER (no network)
┌────────────────────────────────────────┐          ┌──────────────────────────────┐
│ Agent    keys, loop, limits            │          │ /testbed   repository        │
│ Worker   the model's code              │          │ conda "testbed" dependencies │
│ MCP server  tools ─────────────────────┼─docker──▶│ tests, git diff, edits       │
│                                        │   exec   │                              │
└────────────────────────────────────────┘          └──────────────────────────────┘
```

- **The code the model writes runs in the worker, on the host**, under the sandbox restrictions. From
  there it cannot import the project or read `/testbed` directly.
- **The repository and its tests are in the container.** To touch them, the model's code calls the
  tools, and the MCP server runs them inside the container with `docker exec`.
- If the model needs to **run the project's code** (for example, to reproduce the error), it uses
  `run_command`, which runs the command inside the container, in the `testbed` environment.

This is option (b) allowed by the subject: sandbox on the host and MCP tools that reach into the
container.

### 25.4 What Agent Smith does at the start

1. **Records the start time**, reads the task and computes the deadline: 900 seconds minus 20 kept
   for cleanup.
2. **Prepares the provider client** with the given model and URL.
3. **Gets the image**: `docker image inspect <image>`; if it does not exist, `docker pull <image>`.
4. **Starts the container**:
   `docker run -i --rm --name agent-smith-<random> --network none <image> cat`
   - `--network none`: the project's code cannot reach the internet.
   - `cat` and `-i`: the container lives as long as the agent keeps its standard input open. If the
     agent dies, even with `kill -9`, the container stops and `--rm` removes it (section 23.3).
5. **Waits until it is running** and checks with `docker exec` that `/testbed` has content.
6. **Starts the SWE-bench MCP server** and passes it, through environment variables, the container
   name, the `eval_script` and the task deadline.
7. **Discovers the tools** and checks that all nine are there.
8. **Builds the two initial messages** (section 25.5) and **starts the worker**.
9. **Enters the loop** (section 19).

### 25.5 How it knows what to fix

**Only from the text it receives.** Nobody tells it which file is wrong or what the fix is.

**The system prompt** teaches it a method, not a solution:

1. Locate the code: `search_function_or_class_definition_in_code` for a definition, `search_code`
   for a pattern and `find_references` to see who uses something.
2. Read it with `read_file` before changing anything.
3. Make the smallest change with `edit_file`, including enough context for the searched text to
   appear only once.
4. Run `run_tests` and read the result: a failure shows what to correct.
5. When the tests pass, submit `final_answer(get_patch())`, and never before `get_patch` shows
   changes.

It also explains that the code runs in a sandbox that cannot import the project, that only what it
prints comes back as an observation, that it must not invent observations and that it must not look
for the official fix or a remembered patch. At the end it includes the tools **manual**.

**The task message** contains the identifier, the repository, the issue text, the hints if any, and
the sentence "The checkout is at /testbed. Inspect it before editing."

From there, the model reasons as a person would. In this example, the issue says that
`coth(log(tan(x)))` fails and the error points to `hyperbolic.py`, so the sensible first step is to
find where `coth` is defined. In this task the hint almost gives the answer away. Other tasks have
no hints, or much less clear ones. Using them is legitimate: they are part of the task the moulinette
provides.

**What the agent does not see:**

- **The original fix**: it is neither in the image nor in the task.
- **The new tests that will decide the result**: they are not in the image's repository; the
  evaluation script adds them when it runs and removes them when it finishes (section 25.6).
- **The `eval_script`**: the MCP server holds it, not the container or the prompt. The model only
  sees the result of running it.
- **The internet**: neither the worker nor the container has network access.

### 25.6 The evaluation script and `run_tests`

Every task comes with its `eval_script`. For `sympy__sympy-13480` it does this, in order:

1. Activates the `testbed` environment and enters `/testbed`.
2. Shows the git status and **reinstalls the project** (`pip install -e .`), so the code is used as
   it is at that moment, with the agent's changes.
3. **Restores the test file** to its original version and **adds the new tests** with a small patch.
   In this case, two assertions in `test_hyperbolic.py`:
   ```
   assert coth(log(tan(2))) == coth(log(-tan(2)))
   assert coth(1 + I*pi/2) == tanh(1)
   ```
   They are exactly the cases from the issue: they fail with the original code and pass with the fix.
4. Writes the marker `>>>>> Start Test Output`, runs the tests of that file and writes
   `>>>>> End Test Output`.
5. **Puts the test file back as it was**, so it is not part of the patch.

The **`run_tests`** tool runs this script inside the container and **returns only what is between the
two markers**, which is where the test result is. The rest (installation, git status) would only use
up tokens. If it cannot find the markers, it returns the whole output, truncated.

This way the agent can tell whether its fix works **without ever seeing the tests** or the fix.

### 25.7 Real example: the task solved in five iterations

> **Example.** A run of Agent Smith on this task in September 2026 with the `codestral-2508` model.
> The data comes from that run's `solution.json`.

Each row is one iteration. The middle column is the `sandbox_input` (the code the model wrote) and the
right column a summary of the `sandbox_output` (the observation it received):

| Step | Code written by the model | Observation received |
| --- | --- | --- |
| 1 | `print(search_function_or_class_definition_in_code(name="coth"))` | `/testbed/sympy/functions/elementary/hyperbolic.py:537: class coth(HyperbolicFunction):` |
| 2 | `print(read_file(filepath="/testbed/sympy/functions/elementary/hyperbolic.py", start_line=585, end_line=595))` | The numbered lines. Line 589 is `cothm = coth(m)` and line 590, `if cotm is S.ComplexInfinity:` |
| 3 | `print(edit_file(filepath=".../hyperbolic.py", old_str="if cotm is S.ComplexInfinity:", new_str="if cothm is S.ComplexInfinity:"))` | `Edit applied successfully.` |
| 4 | `print(run_tests())` | The list of tests, ending in `tests finished: 45 passed` |
| 5 | `final_answer(get_patch())` | The patch |

Behind each row there is a full iteration: request to the model, block extraction, execution in the
worker, tool request to the agent, MCP call to the server, `docker exec` in the container and the
result coming back as an observation (section 16.3).

Totals: 5 iterations, 9,772 input tokens, 222 output tokens and 13 seconds.

The submitted solution:

```diff
diff --git a/sympy/functions/elementary/hyperbolic.py b/sympy/functions/elementary/hyperbolic.py
@@ -587,7 +587,7 @@ def eval(cls, arg):
                 x, m = _peeloff_ipi(arg)
                 if m:
                     cothm = coth(m)
-                    if cotm is S.ComplexInfinity:
+                    if cothm is S.ComplexInfinity:
                         return coth(x)
```

### 25.8 The tools in practice

| Tool | Typical use | What it returns | Limits |
| --- | --- | --- | --- |
| `search_function_or_class_definition_in_code` | Finding where something named in the issue is defined | `path:line: content` | 50 matches |
| `search_code` | Searching for text or a regular expression | `path:line: content` | 50 matches |
| `find_references` | Seeing who uses a function or class | `path:line: content` (text search for the name) | 50 matches |
| `list_files` | Getting oriented in a folder | One path per line | 4,000 characters |
| `read_file` | Reading a range of lines | `number: line` | 4,000 characters |
| `edit_file` | Replacing an exact fragment | Confirmation or the reason for rejection | — |
| `run_command` | Reproducing the error, running the project's code | Exit code, output and errors | 4,000 characters; 120 s |
| `run_tests` | Checking the fix | The part of the script between markers | 4,000 characters |
| `get_patch` | Viewing or submitting the changes | The full diff, or "No changes yet." | **Never truncated** |

When an output exceeds 4,000 characters, **the beginning and the end** are kept with a notice of how
many characters were omitted. When a search reaches 50 matches, it warns that the pattern should be
narrowed.

All paths are expressed as `/testbed/...`, and any path leaving the repository is rejected.

`edit_file` rejects three cases and explains why, so the model does not believe it changed something
it did not:

- the searched text **does not appear**, or **appears several times** (it says on which lines);
- the new text is **identical** to the old one;
- the resulting Python file **would not compile**.

### 25.9 The patch

`get_patch` runs `git -c core.fileMode=false diff` inside the container:

- `git diff` shows the changes against the repository's commit, that is, everything the agent has
  edited.
- `core.fileMode=false` makes git **ignore file permission changes**, which are not code changes and
  would clutter the patch. It is the command the subject specifies.

Since the `eval_script` restores the test file when it finishes, the patch only contains the agent's
changes. If there are no changes, `get_patch` returns "No changes yet.". That is why, after the loop,
the agent checks that the final answer contains `diff --git`: if not, the task is marked as failed
even if the model called `final_answer`.

### 25.10 After submission

**In Agent Smith:**

1. The worker and the MCP server are closed.
2. `cat`'s standard input is closed: the container stops and `--rm` removes it. To be safe,
   `docker rm -f` is also run.
3. `solution.json` is written with the patch, every step and the totals. If cleanup fails or the
   total time exceeds 900 seconds, the result is marked as failed.

**In validation**, the moulinette:

1. Checks that the solution looks like a patch.
2. Starts **its own clean container** from the same image: it reuses nothing from the agent.
3. Applies the patch with `git apply`, trying more tolerant variants if it fails.
4. Runs the same evaluation script.
5. Analyses each test's result with SWE-bench's official logic. It requires the tests that had to go
   green to pass (**FAIL_TO_PASS**) and the ones that already passed to keep passing
   (**PASS_TO_PASS**). Only a full resolution counts.
6. Removes its container.
7. Checks the `solution.json` metrics: iterations, input tokens, output tokens and time.

Only if both correctness and metrics are right does it print `Overall: PASSED`.

### 25.11 Why it sometimes fails

The example task is a simple one. In hard ones, failures usually come from the model, not the
infrastructure:

- **It edits the wrong file**, even though the test error points to the right one.
- **It gets stuck in a loop**: it repeats the same search or edit, or undoes and redoes its own
  change.
- **It exhausts the 30 iterations or the token budget** before the tests pass.
- **It tests by hand and never sees its fix break other tests**: it runs a script with
  `run_command` instead of `run_tests`.
- **The provider fails**: quota exhausted, the service overloaded for too long, or a request
  refused for being too large.

**Before blaming the model, check the agent.** One failure in this list used to read "it writes the
fix as sandbox code instead of editing the file". Replaying the saved runs showed that, in four of
the seven cases examined, the reply did contain the `edit_file` call, in a later block that the agent
never ran (section 29.1).

The tool decisions (rejecting edits that change nothing, bounding outputs, returning only the test
result) exist to give the model clear observations and reduce these failures, but they do not
eliminate them. Part IV tells what was measured.

---

# Part IV. Lessons learned

This part collects what building and measuring Agent Smith taught between September and October
2026. Facts about providers and models carry their date: free plans change quickly, so every figure
here is a snapshot to check again before relying on it. The numbers come from saved `solution.json`
files, validated with the moulinette, and most of them are detailed in the project's benchmark
report.

## 26. Free models in practice

### 26.1 Catalogues change without notice

- Groq retired `llama-3.3-70b-versatile` within two months of our first tests.
- On 29 September 2026 OpenRouter stopped offering useful free models. The model chosen for MBPP
  twelve days earlier disappeared with them, and the agent had to move to another provider.
- When a model loses its free variant, its identifier may still exist but answer 404 with a message
  saying it is not available for free.

What to do about it:

- **Before any session that matters, send one minimal request to each model you depend on** and read
  the status code: 200, it works; 404, it was retired; 429 or 503, momentary saturation, try again
  later; 401, a key problem.
- **Ask the provider's API, never a third-party list.** A directory of "free models", dated two
  months earlier, still listed one that no longer was.
- **A hand-written test request needs a `User-Agent` header.** Groq sits behind Cloudflare, and a
  request without one receives `403 error code: 1010`, which looks like a revoked key and is not. The
  official SDK sends the header by itself.

### 26.2 Quotas, accounts and time

Measured with Groq on 18 September 2026, reading the rate-limit headers of a minimal request:

- `x-ratelimit-limit-requests: 1000` and `x-ratelimit-reset-requests: 1m26.4s`. Those 86.4 seconds
  are 86,400 / 1,000: **the daily quota is replenished continuously**, one request every 86.4
  seconds, not at midnight.
- The headers show requests per day and tokens per minute, but **not tokens per day**. That limit
  has to be tracked by hand.
- Three keys, one request each, all reported 999 requests left. Keys from one account would have
  shared the counter, and the third would have shown 997. This is a quick way to check that keys
  are really independent.

Other providers count differently: with Google AI Studio the quota belongs to the **project** the key
was created in, and OpenRouter's free models allowed about **50 requests per day** per account. On
one day all its keys were exhausted by earlier tests, and every task failed with 429. Read each
provider's terms of use before opening several accounts.

**A 429 costs time, not tokens.** The provider refuses before generating, so the request consumes
nothing. With Groq's 8,000 tokens per minute, one hard task took 465 seconds with keys from two
accounts and 93 seconds with three. The extra accounts bought time, not quota: a full run of three
SWE-bench tasks used about 81,000 tokens, well within the 200,000 tokens per day that the provider
documents for one account.

### 26.3 The refusal that no wait fixes

Every error Groq returned for `qwen/qwen3.8-27b` on its free plan named a limit of **7,000 input
tokens**. Any single request above it is answered with **HTTP 413, "Request too large"**, and is
never served, however long the client waits. The documentation only mentioned 8,000 tokens per
minute.

On 29 September 2026 a run of the hardest task had a correct patch by step 17 (the moulinette
accepted it afterwards). The next request weighed 7,073 tokens, Groq refused it with 413, and the
client stopped, as it does with any 4xx other than 429. The history budget of section 19.4, about
17,000 tokens at that point, had never kept that model under 7,000.

The fix is the **maximum input per request** of section 24.1, set to 6,000 for that model only. The
margin is there because the agent's own estimate (about four bytes per token) counted roughly 10%
fewer tokens than Groq did. In the next full run, the largest request measured 6,425 tokens. A cap
for every model was rejected: it would change runs that already passed.

### 26.4 Free means free

The subject allows free plans only: no paid plans, purchased credits or accounts with billing
enabled. Two offers looked useful and break that rule:

- **A one-off credit purchase on a router.** On OpenRouter, buying 10 dollars once raises the daily
  limit of its free models from 50 to 1,000 requests, and those models still cost nothing per token.
  It is still a purchased credit.
- **A provider that needs a card before it generates anything.** Cerebras answered every generation
  request with `HTTP 402 payment_required` until a payment method was added. That is a
  billing-enabled account.

### 26.5 The same model varies with the hour

- On the afternoon of 14 September 2026, Google's endpoint returned 503 almost continuously. The runs
  from that afternoon were discarded and repeated.
- On 18 September 2026 `codestral-2508` changed within an hour. In the morning its replies were about
  2,100 characters long and it edited constantly. An hour later they were about 215 characters, with
  a stray `<!-- omit in toc -->` at the end, and it read files in a loop: 128 `read_file` calls
  against 34 `edit_file` in 172 steps.

When a model suddenly behaves very differently, suspect the provider before touching the code, and
switch to another model rather than change the agent.

## 27. Choosing a model

### 27.1 The comparison

Ten models ran the same three SWE-bench tasks (`sympy__sympy-13480`, `sympy__sympy-18189` and
`django__django-11066`) between 14 and 17 September 2026, one run per model and task, all on free
plans:

| Model | Passed | Iterations | Input tokens | What stood out |
| --- | ---: | ---: | ---: | --- |
| `qwen/qwen3.8-27b` | 3/3 | 19 | 54,448 | Slow only because of 429 waits (376 s in total) |
| `codestral-2508` | 3/3 | 14 | 34,139 | The fewest tokens; needs an extra stop sequence (section 28.3) |
| `gemini-3.5-flash-lite` | 3/3 | 22 | 77,425 | Steady, one retry in 76 steps |
| `dots-3-note-preview` | 3/3 | 27 | 88,112 | 2.6 times the output tokens of the previous one |
| `ling-3.0-flash-vl` | 2/3 | 25 | 90,962 | Once submitted an answer that was not a patch |
| `gemini-3.1-flash-lite` | 2/3 | 54 | 515,988 | 29 of its 54 steps came back empty |
| `gemini-3.5-flash` | 0/3 | 29 | 169,242 | Only 41% of its attempts returned a usable answer |
| `gemini-3.8-flash` | 0/3 | 22 | 138,979 | 50 s per step |
| `nemotron-3.5-lightning` | 0/3 | 14 | 69,790 | 23 s per step and request timeouts |
| `gemma-4-31b-it` | 0/3 | 3 | 0 | Every request refused with 429 |

### 27.2 What decided

- **The hardest task, not the average.** Four models passed the three tasks above. On
  `sympy__sympy-14711`, which is much harder, `qwen/qwen3.8-27b` passed five attempts out of five,
  `codestral-2508` about one in nine, and `gemini-3.5-flash-lite` none (partly because of a bug in the
  agent, section 29.1). That is why Qwen was chosen on 17 September 2026, with `codestral-2508` as the
  first backup.
- **Speed per step is a hard limit.** At 50 seconds per step, 30 iterations take 1,500 seconds,
  more than the 900 allowed, whatever the model's quality.
- **Empty answers are expensive.** Each retry resends the whole request, and its input counts
  against the task's budget. `gemini-3.1-flash-lite` used all 300,000 input tokens of one task in 22
  iterations.
- **For MBPP, availability decided twice.** The first choice disappeared from its provider on 29
  September 2026. `gemini-3.5-flash-lite` replaced it: five randomly drawn tasks out of five on three
  different days, the third time on a school machine, and four out of five in another run that day.

### 27.3 How far to trust a comparison

- **One run per cell is a direction, not a rate.** The same agent, model and tasks took 8, 7 and 7
  iterations one day and 6, 11 and 9 another. A difference smaller than about four iterations per
  task cannot be told apart from chance.
- **A row full of provider errors measures the provider that day** at least as much as the model.
- **Measure again before the date that matters.** A choice made in September can be wrong in
  January.

## 28. What measuring the agent taught

### 28.1 Finding the file is not the problem; submitting is

Two intermediate metrics (section 11.3) were measured on every passing run:

- **The first step that reads or edits a file of the final patch** was 1, 2 or 3, and 2 in most
  runs. Every model finds the right file quickly.
- **The iterations between "the tests pass" and `final_answer`** were between 1 and 3. Some models
  kept re-running the tests, printing `git diff` or calling `get_patch` before submitting. With
  `gemini-3.5-flash-lite` on `sympy__sympy-13480`, the tests passed at step 5 and it submitted at
  step 8: those last three steps cost 16,628 of the task's 27,767 input tokens, 60%.

Late steps are the most expensive ones, because each resends the whole grown history.
`codestral-2508` and `qwen/qwen3.8-27b` submitted right after their tests passed in every passing
run of the comparison.

### 28.2 A correct fix changes nothing if the model does not use it

`run_tests` used to return the first and last 2,000 characters of the evaluation script's output.
The beginning was `git status` noise and the end deprecation warnings: **the test summary fell in the
omitted middle**, and the exit code it reported belonged to the script's last command, not to the
tests. It was fixed to return only the part between the script's markers (section 25.6).

The fix was right, and it changed nothing: the model being measured did not call `run_tests` once in
four runs, because it tested with its own `run_command`. The iterations after the tests passed did not
move either, so the hypothesis behind the fix was wrong. **Measure whether the model uses a piece
before expecting that piece to help.**

### 28.3 The largest effect came from one line of configuration

`codestral-2508` never writes `<end_code>`, so the stop sequence never fired. After its code block it
went on writing an invented `Observation:` (the contents of a file it had not read), then another
block, until the 600-token cap. Adding `"Observation:"` to its stop sequences changed this, with the
same code, tasks and day:

| | Without | With |
| --- | ---: | ---: |
| Tasks passed (six tasks) | 4 | 5 |
| Replies with an invented observation | 27 | 0 |
| Replies cut at the 600-token cap | 21 | 0 |
| Output tokens | 15,975 | 4,113 |

On `pydata__xarray-4629` the run went from an exhausted output budget after 20 iterations to a pass
in 5. Where the model had invented nothing, the numbers did not move, which is what a change acting
through a single mechanism should produce. The other models keep a single stop sequence: adding
the second one to them was never measured.

### 28.4 Prompt changes that did not help

| Change | Result | Decision |
| --- | --- | --- |
| Removing the warning "the sandbox cannot import the project" | No measurable difference for that model, which never tried to import anyway | Kept: three lines, added for a failure seen with another model |
| Telling the model "you already ran exactly this code and got exactly this result" | Ignored: the model repeated the same call until the iteration limit. 1 pass in 4, against 1 in 2 without it | Discarded |
| A second example showing how to finish: edit, test and submit | Obeyed, but the model still looped, only on a different call; and its failures became more expensive (272,593 input tokens on average, against 179,684) | Discarded |
| A shorter MBPP prompt | Saved tokens and failed a task the original prompt solved | Discarded |

On the hardest task, a model's loops resisted every wording tried. A change that shows no effect is
removed rather than kept "just in case".

### 28.5 Neither the whole history nor a small window

With the whole history, one run spent 296,410 of its 300,000 input tokens. With a fixed window of
the last three exchanges, the model forgot it had already edited a file and re-read the same ranges
22 times. The budget-based window of section 19.4 came from those two failures.

### 28.6 Refused edits waste many steps

In six runs of the hardest task, 47 of the 155 steps, 30%, were edits that `edit_file` refused, 31
of them because the searched text did not appear at all ("found 0"). When the text appears several
times, `edit_file` says on which lines; when it appears zero times, it says nothing more. Whether a
hint there would help has not been measured.

## 29. Bugs that looked like model failures

### 29.1 The extractor ran the example

For two weeks, analyses said that one model "defines the function inside the sandbox instead of
editing the file". The real cause was the agent.

At that time the extractor ran **the first closed Python block** of a reply. Running the extractor
again over every saved reply (217 runs, 1,502 replies) showed 17 steps, in 9 runs, 8 of them failed,
where the first block was an example and a later block held the real call (`edit_file`,
`run_command` or `run_tests`). Twelve of the 17 were on the hardest task. In one of them the model had
written a valid fix at step 27 (the moulinette accepted it when applied by hand); the agent ran the
example instead, and the run ran out of input budget at step 30.

Three rules were compared on the same saved replies before changing any code:

| Rule | Effect on the 1,502 replies |
| --- | --- |
| Run the last block | 16 replies would have submitted before seeing the result of their own action |
| Run every block | In 13 of 180 replies with several blocks, the blocks do not compile together, and the examples run too |
| Run the first block that calls a discovered tool or `final_answer` | Fixes exactly the 17 cases and changes none of the other 1,485 |

The third rule was adopted on 1 October 2026 (section 21.1). **Keeping every reply made this possible:
a candidate rule can be replayed over all past runs before it is written.**

### 29.2 A correct patch lost to the size of a request

Section 26.3: a provider refusal looked like a failed task, and the patch was already right.

### 29.3 A false pass

A model once submitted the text "No changes yet.", which `get_patch` returns when nothing has been
edited, and the agent counted it as solved. Since then a SWE-bench answer only counts as a success if
it contains `diff --git` (section 18).

### 29.4 Timeouts on Python 3.10

In an early version, a provider timeout ended the task with the bare message `TimeoutError:`. On
Python 3.10, `asyncio.TimeoutError` is not the built-in `TimeoutError`; they only became the same
class in Python 3.11. Catch the exception the library really raises. Today the official SDK reports a
timeout with its own error class, and the client treats it as unknown usage (section 24.4).

### 29.5 Estimates are not measurements

The agent's token estimate is useful to avoid sending a request that would certainly exceed the
budget, but it counted about 10% fewer tokens than one provider. Leave a margin when an estimate
guards a hard limit, and record only what `usage` reports.

## 30. Running on shared machines with rootless Docker

The school machines run **rootless Docker**: the Docker daemon runs as your own user instead of as
the administrator. Several things that always worked at home failed there on 4 October 2026. All of
them were solved without changing the agent's logic.

### 30.1 Where the images go

- **The home folder is too small.** Rootless Docker stores images under your home, and the first
  download failed with `no space left on device`.
- **A network disk does not work.** On the shared network storage (sgoinfre) the download failed with
  `failed to Lchown "/etc/gshadow" ... invalid argument`.
- **The machine's local disk (goinfre) works.** Point Docker's data directory there and restart the
  daemon:

```bash
docker system prune -af
mkdir -p ~/.config/docker /goinfre/$USER/docker
echo '{ "data-root": "/goinfre/'$USER'/docker" }' > ~/.config/docker/daemon.json
systemctl --user restart docker
docker info 2>/dev/null | grep "Docker Root Dir"     # must show /goinfre/...
```

The local disk belongs to one machine and may be wiped, so on another computer the step has to be
repeated and the images downloaded again. SWE-bench images take between 4 and 7.6 GB each; the disk
filled up once while they were being downloaded.

### 30.2 `--cpus` is rejected

The MBPP test container used to run with `--cpus 0.5`. On rootless Docker it failed with:

```
docker: Error response from daemon: NanoCPUs can not be set, as your kernel does not support
CPU CFS scheduler or the cgroup is not mounted
```

`run_tests` never started, and the model submitted without having seen a single test result. The
option was removed; the memory limit kept working. `docker info | grep -i rootless` tells whether a
machine runs rootless Docker.

### 30.3 Download the images in advance

- **The MBPP image** (`python:3.11-slim`) is downloaded neither by `run_tests`, which uses
  `--pull never`, nor by the moulinette. Without it, `run_tests` answers "Public tests could not
  start." with a Docker error, and the moulinette marks correct solutions as failed. Check it with:

  ```bash
  docker run --rm --network none python:3.11-slim python -c "print('ok')"
  ```

- **SWE-bench images** are downloaded by the agent if they are missing, but inside the task's 900
  seconds. Download them before.
- **A warning sign in any `solution.json`**: an observation saying "Public tests could not start." or
  "Docker error" means the machine failed, not the model.

### 30.4 The moulinette, rootless Docker and file owners

The agent solved a SWE-bench task on a school machine, but the moulinette's validation failed with:

```
failed to Lchown "/tmp/patch.diff" for UID <your UID>, GID <your GID>: lchown /tmp/patch.diff: invalid argument
```

The moulinette copies the patch into its container as a `tar` archive, and the archive records your
user identifier (UID) as the file's owner. Rootless Docker can only assign the identifiers of its own
range, so it rejects the file. The exception also leaves the moulinette's validation container
running.

The fix needs no code change: **run the SWE-bench commands inside `rootlesskit bash`**. `rootlesskit`
is the program rootless Docker itself starts with; `rootlesskit bash` opens a shell inside a *user
namespace*, an isolated view of user identifiers in which your user is UID 0. From there the archive
carries UID 0, which rootless Docker maps back to you. Three SWE-bench tasks were validated this way on
4 October 2026. MBPP does not copy files into containers and works outside that shell too.

### 30.5 One Python environment per project

If the variable `UV_PROJECT_ENVIRONMENT` points at a single environment, the agent and the moulinette
share it, and every `uv run` uninstalls one project's packages to install the other's (26 packages
each time). A server started by one of them can lose its packages while it is starting. Unset the
variable so each project keeps its own environment.

On a network disk the first run of a fresh environment is also slow, because packages are compiled
the first time they are imported. A server may take longer than expected to start listening, so run
everything once before it matters.

## 31. Stopping the agent

Section 23.3 explains why the SWE-bench container disappears even if the agent is killed with
`kill -9`. These are the ways of stopping it that were tested on 15 September 2026:

| How | Result |
| --- | --- |
| `kill -9` to the agent's Python process | Container removed in under 6 seconds |
| Ctrl+C in the terminal | Container removed; it prints `Interrupted: no solution file was written.` and exits with code 130 |
| SIGTERM to the Python process | Container removed |
| `kill -9` **to the `uv` process only** | Python keeps running, and so does the container, until the agent ends normally |

The last row needs explaining. `uv run` starts Python as a **child process**. SIGKILL cannot be caught
(section 7.4), so `uv` dies without passing anything on, and its child keeps working. The container
is not orphaned: the agent will close it when it finishes. To stop the agent, kill the Python process,
for example with `pkill -9 -f "bin/python3 -m agent_swebench"`, which matches the Python child
and not `uv`.

An earlier version printed a full `KeyboardInterrupt` traceback on Ctrl+C. Nothing was left behind,
but a traceback looks like a crash, so it was replaced with that single line.

## 32. A working method

- **Change one thing at a time** and compare with the same model, tasks and day. When conditions are
  compared over several runs, alternate them, so that the provider's changes during the day affect
  both alike.
- **Keep every `solution.json`** next to its task and its validation, failures included. The most
  useful bug fix of the project came from replaying them (section 29.1).
- **Trust the moulinette, not `success`.** `success` is what the agent believes; validation decides.
- **Read the step before blaming the model.** Compare `llm_output`, what the model wrote, with
  `sandbox_input`, what the agent ran. If they differ, the problem may be the agent.
- **Check the models on the day**, and write every fact about a provider with its date.
- **Read where a script writes its results before running it.** Some third-party scripts save their
  results next to their own folder, which may not be yours.
- **Prefer deleting a change that shows no effect.** Every line has to be explained later.
