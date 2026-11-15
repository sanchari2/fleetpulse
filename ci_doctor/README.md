# ci_doctor

Reads a failed GitHub Actions run and posts a diagnosis as a pull-request
comment: root cause, the log lines that prove it, and the fix.

## Why it exists

A red build usually has one line that matters, buried in a few thousand lines of
setup output. Reading it is five minutes of context switching; explaining it is
what a colleague does when they walk over. This automates the walk-over.

## How it works

1. `.github/workflows/ci-doctor.yml` triggers on `workflow_run` completion of
   `ci`, only when the run failed and only for pull requests.
2. `client.collect_failed_steps` lists the run's jobs, keeps the failed ones, and
   downloads each job log.
3. `client.tail_lines` keeps the **last 400 lines** of each log. Not the whole
   thing: setup noise dominates, and a smaller prompt is a smaller blast radius
   if a secret ever leaks into an `echo`.
4. `client.call_claude` sends those tails to the model with a system prompt that
   forbids guessing. A refusal, an empty answer or a non-200 moves on to the next
   configured model; if every model declines, the comment says so.
5. `cli.build_comment` renders Markdown and posts it to the PR.

## Run it locally

```bash
pip install -r requirements.txt

# dry run against a real failed run you can read
GITHUB_TOKEN=ghp_... ANTHROPIC_API_KEY=sk-ant-... \
  python -m ci_doctor.cli --repo you/fleetpulse --run-id 12345 --dry-run
```

`--dry-run` prints the comment instead of posting it. Without `--pr` it also
prints, so you can inspect the body before wiring it into a workflow.

## Behaviour that matters

| Situation | What happens |
| --- | --- |
| No failed jobs | Prints a note, exits 0 |
| Model refuses | Tries `CLAUDE_FALLBACK_MODELS`, then posts a note explaining why |
| API key missing | Posts a note naming the missing variable, exits 0 |
| GitHub API error | Logs it, exits 0 |
| Posting the comment fails | Logs the HTTP status, exits 0 |

Exit code is always 0 unless the arguments are unusable (2). CI Doctor must
never turn one red build into two confusing ones.

## Tests

`tests/test_ci_doctor.py` covers log trimming, prompt assembly, refusal
fallbacks, the honest "no diagnosis" comment, and every CLI path, with a fake
HTTP session — no network, no keys.
