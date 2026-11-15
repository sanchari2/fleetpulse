"""Thin clients for the two APIs CI Doctor needs.

Both are plain HTTPS with an injectable `requests`-compatible session, so the
whole module is testable without a network or an API key.

Design notes
------------
* Only the tail of a failed step is sent to the model. Build logs contain
  environment noise and occasionally secrets that leaked into an echo; sending
  400 lines instead of 40,000 keeps the prompt small and the blast radius small.
* A refusal is a real answer. If the model declines, we try the next configured
  model once, and then give up honestly instead of pretending to diagnose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

GITHUB_API = "https://api.github.com"
ANTHROPIC_API = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

# The model id is configuration, not code: set CLAUDE_MODEL to a model your
# account can call. If your provider names models differently, this is the one
# place to change it.
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_LOG_LINES = 400

SYSTEM_PROMPT = (
    "You are a CI doctor. You are given the name of a failed GitHub Actions job "
    "and the tail of its log. Explain the failure to the engineer who wrote the "
    "change.\n\n"
    "Rules:\n"
    "- Be specific and short. No preamble, no apology, no restating the log.\n"
    "- Quote the exact log line(s) that prove your diagnosis.\n"
    "- If the log does not contain enough evidence, say what to look at next "
    "instead of guessing. A wrong root cause costs more than an honest 'unknown'.\n"
    "- Format exactly as:\n"
    "**Root cause** — one or two sentences.\n"
    "**Evidence** — the log lines, in a fenced block.\n"
    "**Fix** — one to three concrete steps.\n"
)


class DoctorError(RuntimeError):
    """Any failure that means we cannot produce a diagnosis."""


class RefusalError(DoctorError):
    """Every candidate model declined to answer."""


@dataclass
class FailedStep:
    """One failed job and the tail of its log."""

    job_name: str
    job_url: str
    log: str
    failed_steps: list[str] = field(default_factory=list)


@dataclass
class Diagnosis:
    """What the model said, and which model said it."""

    text: str
    model: str


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def list_jobs(session, repo: str, run_id: str, token: str) -> list[dict]:
    """Every job in a workflow run."""
    response = session.get(
        f"{GITHUB_API}/repos/{repo}/actions/runs/{run_id}/jobs",
        headers=_auth_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        raise DoctorError(f"listing jobs failed: HTTP {response.status_code} {response.text[:200]}")
    return list(response.json().get("jobs") or [])


def failed_jobs(jobs: list[dict]) -> list[dict]:
    """Filter to jobs whose conclusion is a failure."""
    return [job for job in jobs if job.get("conclusion") in {"failure", "timed_out", "cancelled"}]


def job_log(session, repo: str, job_id: int, token: str) -> str:
    """Download a job's log as text. GitHub redirects, so follow them."""
    response = session.get(
        f"{GITHUB_API}/repos/{repo}/actions/jobs/{job_id}/logs",
        headers=_auth_headers(token),
        timeout=60,
        allow_redirects=True,
    )
    if response.status_code != 200:
        raise DoctorError(f"job {job_id} log unavailable: HTTP {response.status_code}")
    return response.text


def tail_lines(text: str, limit: int = DEFAULT_MAX_LOG_LINES) -> str:
    """Last `limit` lines of a log, with a marker showing what was dropped."""
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    kept = lines[-limit:]
    return f"...[{len(lines) - limit} earlier lines omitted]...\n" + "\n".join(kept)


def failed_step_names(job: dict) -> list[str]:
    """Names of the steps that failed, for the prompt header."""
    return [
        str(step.get("name"))
        for step in job.get("steps") or []
        if step.get("conclusion") in {"failure", "timed_out"}
    ]


def collect_failed_steps(
    session, repo: str, run_id: str, token: str, limit: int
) -> list[FailedStep]:
    """Fetch every failed job with a trimmed log."""
    steps: list[FailedStep] = []
    for job in failed_jobs(list_jobs(session, repo, run_id, token)):
        try:
            log = job_log(session, repo, int(job["id"]), token)
        except DoctorError as exc:
            log = f"(log unavailable: {exc})"
        steps.append(
            FailedStep(
                job_name=str(job.get("name", "unknown job")),
                job_url=str(job.get("html_url", "")),
                log=tail_lines(log, limit),
                failed_steps=failed_step_names(job),
            )
        )
    return steps


def build_prompt(steps: list[FailedStep], repo: str, run_id: str) -> str:
    """Assemble the user message: what ran, what failed, and the log tails."""
    if not steps:
        raise DoctorError("no failed jobs to diagnose")
    parts = [f"Repository: {repo}", f"Workflow run: {run_id}", ""]
    for index, step in enumerate(steps, 1):
        parts.append(f"## Failed job {index}: {step.job_name}")
        if step.failed_steps:
            parts.append("Failed steps: " + ", ".join(step.failed_steps))
        if step.job_url:
            parts.append(f"Job URL: {step.job_url}")
        parts.append("Log tail:")
        parts.append("```")
        parts.append(step.log.strip())
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def _text_from_response(payload: dict) -> str | None:
    blocks = payload.get("content") or []
    chunks = [
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    text = "\n".join(chunk for chunk in chunks if chunk).strip()
    return text or None


def call_claude(
    prompt: str,
    *,
    api_key: str,
    models: list[str],
    session,
    base_url: str = ANTHROPIC_API,
    max_tokens: int = 1200,
) -> Diagnosis:
    """Ask each candidate model in turn; a refusal or empty answer moves on."""
    if not api_key:
        raise DoctorError("ANTHROPIC_API_KEY is not set")
    if not models:
        raise DoctorError("no model configured")

    last_reason = "no attempt made"
    for model in models:
        response = session.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        if response.status_code != 200:
            last_reason = f"{model}: HTTP {response.status_code} {response.text[:200]}"
            continue
        payload = response.json()
        if payload.get("stop_reason") == "refusal":
            last_reason = f"{model}: refused"
            continue
        text = _text_from_response(payload)
        if text is None:
            last_reason = f"{model}: empty response"
            continue
        return Diagnosis(text=text, model=model)

    raise RefusalError(f"no usable answer ({last_reason})")


def models_from_env(env: dict[str, str] | None = None) -> list[str]:
    """Primary model plus any fallbacks, de-duplicated, in order."""
    source = os.environ if env is None else env
    primary = (source.get("CLAUDE_MODEL") or DEFAULT_MODEL).strip()
    fallbacks = [
        item.strip()
        for item in (source.get("CLAUDE_FALLBACK_MODELS") or "").split(",")
        if item.strip()
    ]
    ordered: list[str] = []
    for model in [primary, *fallbacks]:
        if model not in ordered:
            ordered.append(model)
    return ordered
