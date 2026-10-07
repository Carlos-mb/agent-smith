"""Pydantic models used by the Agent Smith command-line programs."""

from agent_smith.logging_config import get_logger

from datetime import datetime

from pydantic import BaseModel, Field

logger = get_logger('agent_smith.models')


def current_timestamp() -> str:
    """Return the current local date and time in ISO 8601 format."""
    logger.debug("Entrando en current_timestamp")
    return datetime.now().isoformat()


class StepMetrics(BaseModel):
    """Metrics collected during one agent iteration."""

    step: int = Field(..., description="1-indexed iteration number")
    input_tokens: int = Field(..., description="Tokens sent to the LLM")
    output_tokens: int = Field(..., description="Tokens returned by the LLM")
    request_time_ms: float = Field(
        ..., description="LLM request time in milliseconds")
    api_url: str = Field(default="", description="LLM provider base URL")
    model_name: str = Field(default="", description="LLM model name")
    llm_output: str = Field(default="", description="Raw LLM response")
    sandbox_input: str = Field(
        default="", description="Code sent to the sandbox")
    sandbox_output: str = Field(
        default="", description="Sandbox execution result")
    retries: int = Field(
        default=0, description="Retries used for this request")
    timestamp: str = Field(default_factory=current_timestamp)


class SolutionOutput(BaseModel):
    """Result written by an MBPP or SWE-bench agent."""

    task_id: str
    benchmark: str
    success: bool
    solution: str
    system_prompt: str = ""
    iterations: int
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_time_seconds: float
    steps: list[StepMetrics] = Field(default_factory=list)
    error: str | None = None
    timestamp: str = Field(default_factory=current_timestamp)


class SandboxConfig(BaseModel):
    """Configuration for sandbox restrictions and resource limits."""

    authorized_imports: list[str] = Field(
        default_factory=lambda: [
            "math",
            "math.*",
            "collections",
            "collections.*",
            "itertools",
            "re",
            "json",
            "typing",
            "typing.*",
            "functools",
            "operator",
            "heapq",
            "bisect",
            "copy",
            "string",
            "random",
            "datetime",
            "datetime.*",
            "array",
            "cmath",
        ]
    )
    allowed_directories: list[str] = Field(
        default_factory=lambda: ["/testbed", "/tmp/agent"]
    )
    max_execution_time_seconds: int = Field(default=30, gt=0)
    max_memory_mb: int = Field(default=512, gt=0)


class AgentLimits(BaseModel):
    """Cumulative limits for one task, including setup, MCP waits, and cleanup.

    The shared agent loop owns its counters. The provider receives remaining
    limits as values and returns usage without mutating the loop's state.
    """

    # The CLI takes started_at with monotonic before reading any file. The
    # adapter computes deadline=started_at+max_time_seconds; it does not
    # restart the clock when entering the loop. The time covers setup,
    # retries, tools and cleanup.
    # Check the limits before/after each request and before accepting
    # final_answer. If usage is missing, report a failure and the known
    # subtotals.
    # Limits from subject VI.1 and moulinette/models.py: MBPP
    # 10/6000/1500/120 s; SWE-bench 30/300000/10000/900 s. The moulinette
    # README is out of date.

    max_iterations: int = Field(..., gt=0)
    max_input_tokens: int = Field(..., ge=0)
    max_output_tokens: int = Field(..., ge=0)
    max_time_seconds: float = Field(..., gt=0)


class MBPPTaskInput(BaseModel):
    """Input data for one MBPP task."""

    task_id: int
    task_definition: str
    function_definition: str
    test_imports: list[str] = Field(default_factory=list)
    test_list: list[str] = Field(default_factory=list)


class SWEBenchTaskInput(BaseModel):
    """Input data for one SWE-bench task."""

    instance_id: str
    problem_statement: str
    docker_image: str
    eval_script: str
    hints_text: str = ""
    repo: str = ""
