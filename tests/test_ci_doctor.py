"""CI Doctor: log trimming, prompt building, refusal handling, CLI behaviour."""

from __future__ import annotations

import json

import pytest

from ci_doctor import cli, client


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeSession:
    """URL-substring router. A list of responses is served in order."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.posted: list[tuple[str, dict]] = []
        self.requested: list[str] = []

    def _pick(self, url: str):
        # longest fragment wins, so /logs is not shadowed by /jobs
        for fragment in sorted(self.routes, key=len, reverse=True):
            response = self.routes[fragment]
            if fragment in url:
                if isinstance(response, list):
                    return response.pop(0)
                return response
        raise AssertionError(f"unexpected request: {url}")

    def get(self, url, **kwargs):
        self.requested.append(url)
        return self._pick(url)

    def post(self, url, **kwargs):
        self.requested.append(url)
        self.posted.append((url, kwargs.get("json") or {}))
        return self._pick(url)


def jobs_payload() -> dict:
    return {
        "jobs": [
            {
                "id": 11,
                "name": "test (3.12)",
                "conclusion": "failure",
                "html_url": "https://github.com/o/r/actions/runs/1/job/11",
                "steps": [
                    {"name": "Set up job", "conclusion": "success"},
                    {"name": "pytest", "conclusion": "failure"},
                ],
            },
            {
                "id": 12,
                "name": "image",
                "conclusion": "success",
                "html_url": "https://github.com/o/r/actions/runs/1/job/12",
                "steps": [],
            },
        ]
    }


def claude_ok(text: str = "**Root cause** — a test asserted the wrong threshold.") -> FakeResponse:
    return FakeResponse(payload={"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]})


def claude_refusal() -> FakeResponse:
    return FakeResponse(payload={"stop_reason": "refusal", "content": []})


# -- log handling -------------------------------------------------------
def test_tail_lines_keeps_the_end_and_marks_the_drop():
    text = "\n".join(f"line {i}" for i in range(1, 101))
    trimmed = client.tail_lines(text, 10)
    assert "earlier lines omitted" in trimmed
    assert trimmed.endswith("line 100")
    assert "line 91" in trimmed


def test_tail_lines_leaves_short_logs_alone():
    assert client.tail_lines("one\ntwo", 10) == "one\ntwo"


def test_failed_jobs_filters_on_conclusion():
    assert [job["id"] for job in client.failed_jobs(jobs_payload()["jobs"])] == [11]


def test_failed_step_names():
    job = jobs_payload()["jobs"][0]
    assert client.failed_step_names(job) == ["pytest"]


# -- collection ---------------------------------------------------------
def test_collect_failed_steps_reads_the_log():
    session = FakeSession(
        {
            "/runs/1/jobs": FakeResponse(payload=jobs_payload()),
            "/logs": FakeResponse(text="ERROR: assert 20.0 == 25.0"),
        }
    )
    steps = client.collect_failed_steps(session, "o/r", "1", "t", 400)
    assert len(steps) == 1
    assert steps[0].job_name == "test (3.12)"
    assert "assert 20.0 == 25.0" in steps[0].log
    assert steps[0].failed_steps == ["pytest"]


def test_collect_failed_steps_survives_a_missing_log():
    session = FakeSession(
        {
            "/runs/1/jobs": FakeResponse(payload=jobs_payload()),
            "/logs": FakeResponse(status_code=404, text="not found"),
        }
    )
    steps = client.collect_failed_steps(session, "o/r", "1", "t", 400)
    assert "log unavailable" in steps[0].log


def test_list_jobs_raises_on_bad_status():
    session = FakeSession({"/runs/1/jobs": FakeResponse(status_code=500, text="boom")})
    with pytest.raises(client.DoctorError):
        client.list_jobs(session, "o/r", "1", "t")


# -- prompt -------------------------------------------------------------
def test_build_prompt_contains_the_evidence():
    steps = [client.FailedStep("test (3.12)", "https://x/11", "ERROR: assert 1 == 2", ["pytest"])]
    prompt = client.build_prompt(steps, "o/r", "1")
    assert "## Failed job 1: test (3.12)" in prompt
    assert "Failed steps: pytest" in prompt
    assert "ERROR: assert 1 == 2" in prompt


def test_build_prompt_refuses_an_empty_run():
    with pytest.raises(client.DoctorError):
        client.build_prompt([], "o/r", "1")


# -- the model call -----------------------------------------------------
def test_call_claude_returns_the_text():
    session = FakeSession({"/v1/messages": claude_ok("diagnosis here")})
    diagnosis = client.call_claude("prompt", api_key="k", models=["m1"], session=session)
    assert diagnosis.text == "diagnosis here"
    assert diagnosis.model == "m1"
    assert session.posted[0][1]["model"] == "m1"


def test_call_claude_falls_back_after_a_refusal():
    session = FakeSession({"/v1/messages": [claude_refusal(), claude_ok("second model")]})
    diagnosis = client.call_claude("prompt", api_key="k", models=["m1", "m2"], session=session)
    assert diagnosis.text == "second model"
    assert diagnosis.model == "m2"


def test_call_claude_raises_when_every_model_refuses():
    session = FakeSession({"/v1/messages": [claude_refusal(), claude_refusal()]})
    with pytest.raises(client.RefusalError):
        client.call_claude("prompt", api_key="k", models=["m1", "m2"], session=session)


def test_call_claude_treats_an_empty_answer_as_a_failure():
    session = FakeSession(
        {"/v1/messages": FakeResponse(payload={"stop_reason": "end_turn", "content": []})}
    )
    with pytest.raises(client.RefusalError):
        client.call_claude("prompt", api_key="k", models=["m1"], session=session)


def test_call_claude_needs_a_key():
    with pytest.raises(client.DoctorError):
        client.call_claude("prompt", api_key="", models=["m1"], session=FakeSession({}))


def test_models_from_env_dedupes_and_orders():
    models = client.models_from_env(
        {"CLAUDE_MODEL": "primary", "CLAUDE_FALLBACK_MODELS": "backup, primary, spare"}
    )
    assert models == ["primary", "backup", "spare"]


def test_models_from_env_has_a_default():
    assert client.models_from_env({}) == [client.DEFAULT_MODEL]


# -- the comment --------------------------------------------------------
def test_comment_contains_the_diagnosis_and_provenance():
    steps = [client.FailedStep("test (3.12)", "https://x/11", "log", ["pytest"])]
    body = cli.build_comment(
        client.Diagnosis("**Root cause** — x", "m1"), steps, run_url="https://run/1"
    )
    assert cli.COMMENT_MARKER in body
    assert "`test (3.12)`" in body
    assert "**Root cause** — x" in body
    assert "Model: `m1`" in body
    assert "https://run/1" in body


def test_comment_without_a_diagnosis_is_honest():
    steps = [client.FailedStep("test (3.12)", "", "log")]
    body = cli.build_comment(None, steps, run_url="", note="Reason: no key.")
    assert "Could not produce a diagnosis" in body
    assert "Reason: no key." in body
    assert "unchanged" in body


# -- CLI ----------------------------------------------------------------
def test_cli_requires_repo_and_run_id(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert cli.main([], session=FakeSession({})) == 2
    assert "required" in capsys.readouterr().err


def test_cli_requires_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert cli.main(["--repo", "o/r", "--run-id", "1"], session=FakeSession({})) == 2


def test_cli_dry_run_prints_the_comment(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    session = FakeSession(
        {
            "/runs/1/jobs": FakeResponse(payload=jobs_payload()),
            "/logs": FakeResponse(text="E   assert 1 == 2"),
            "/v1/messages": claude_ok("**Root cause** — off by one"),
        }
    )
    assert cli.main(["--repo", "o/r", "--run-id", "1", "--dry-run"], session=session) == 0
    out = capsys.readouterr().out
    assert "off by one" in out
    assert session.posted[0][0].endswith("/v1/messages")


def test_cli_exits_zero_when_nothing_failed(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    payload = {"jobs": [{"id": 1, "name": "test", "conclusion": "success", "steps": []}]}
    session = FakeSession({"/runs/1/jobs": FakeResponse(payload=payload)})
    assert cli.main(["--repo", "o/r", "--run-id", "1"], session=session) == 0
    assert "nothing to do" in capsys.readouterr().err


def test_cli_posts_a_note_when_the_model_is_unavailable(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    session = FakeSession(
        {
            "/runs/1/jobs": FakeResponse(payload=jobs_payload()),
            "/logs": FakeResponse(text="E   assert 1 == 2"),
            "/comments": FakeResponse(status_code=201),
        }
    )
    code = cli.main(["--repo", "o/r", "--run-id", "1", "--pr", "7"], session=session)
    assert code == 0
    body = session.posted[-1][1]["body"]
    assert "Could not produce a diagnosis" in body
    assert "ANTHROPIC_API_KEY" in body


def test_cli_survives_an_unreadable_run(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    session = FakeSession({"/runs/1/jobs": FakeResponse(status_code=403, text="forbidden")})
    assert cli.main(["--repo", "o/r", "--run-id", "1"], session=session) == 0
    assert "could not read the run" in capsys.readouterr().err


def test_comment_body_is_valid_json_serialisable():
    body = cli.build_comment(None, [], run_url="")
    assert json.loads(json.dumps({"body": body}))["body"] == body
