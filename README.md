# Proofrail — evidence before “done”

A small research-backed experiment on agent reliability, not a general agent framework. It keeps a task's completion claim separate from its saved evidence and checks declared acceptance signals without asking an LLM to grade its own answer.

## Run the demo

From this folder:

```text
python -m unittest -v test_proofrail
python proofrail.py show examples/plan.json
```

Read the displayed command, then copy the printed hash into the run command. A modified plan gets a different hash and will not run under the old approval:

```text
python proofrail.py run examples/plan.json --approve-hash HASH_FROM_SHOW
python proofrail.py verify examples/plan.json
```

To make your own plan and add a test command:

```text
python proofrail.py init task.json --goal "Describe the outcome"
python proofrail.py require-command task.json --name "Unit tests" --argv-json '["python", "-m", "unittest"]' --timeout 60
python proofrail.py show task.json
python proofrail.py run task.json --approve-hash HASH_FROM_SHOW
python proofrail.py verify task.json --json
```

The argv JSON is an argument list, not a shell command. The `show` output binds review to the exact plan bytes; copying its hash is a workflow safeguard against unnoticed plan changes, not proof that a human understood the command. Proofrail executes the command with `shell=False`, captures standard output/error and the actual exit code, and applies a timeout (0.1–300 seconds). Run records are written under `.proofrail/` beside the plan. Verification blocks if the plan differs from the approved hash, if a matching run record is absent, if the captured output digest changed, or if the command exit code is nonzero. Text-file checks remain supported but are weaker.

## Why this shape

Research highlights long, multi-step reliability limits, difficult real-computer interaction, agent safety failures, and the substantial oversight work users perform. See [Research note.md](Research%20note.md) for the cited findings and scope. Proofrail tests one narrow engineering response: use explicit acceptance criteria and inspectable evidence rather than trusting a completion statement.

## Limits — important

- This is a prototype, not a security boundary or production-grade attestation system.
- Direct command checks reduce accidental/fabricated text-log success: the process is launched by Proofrail and its exit status is captured. The reviewed hash ties that run to exact plan bytes. But a command plan is executable code; `show` + hash copying is not a security boundary or proof of informed human review. Execution is not sandboxed, and a malicious test runner or a compromised agent with write access to the plan/record can still defeat this prototype.
- Text-file checks only test for literal content and do **not** prove that the signal is truthful or the task correct.
- A dishonest or compromised agent could choose a weak test, change the test itself, or falsify results outside the captured process. Stronger deployments need isolated/immutable plans, trusted test runners, OS sandboxing, and adversarial evaluation.
- It does not make agents autonomous or remove the need for human judgment on ambiguous, high-impact, or irreversible work. It aims to shrink routine re-checking while keeping authority and accountability explicit.

## Files

- `proofrail.py` — stdlib-only CLI verifier.
- `test_proofrail.py` — unit tests.
- `.github/workflows/tests.yml` — Windows and Linux CI across Python 3.10 and 3.14.
- `examples/` — runnable example plan; its command-run evidence is generated locally and ignored by Git.
- `Research note.md` — findings, citations, rationale, and next experiment.
- `SECURITY.md` — scope and safe-use guidance.
- `LICENSE` — MIT License.
