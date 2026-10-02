# Agent reliability: where the human is still the safety net

*Short research note and prototype rationale — LowKey / Proofrail*

## What the evidence says

Agent autonomy is not one capability. METR measures task-completion time horizons and reports that success falls as tasks become longer and more multi-step; its March 2025 snapshot estimated under 10% success on tasks taking expert humans around four hours. This is an older, benchmark-specific result—not a universal score for today's agents—but it supports reliability over long sequences as a real failure surface.[1]

In OSWorld's 2024 evaluation of 369 tasks across real desktop and web applications, the best tested model reached 12.24% success, compared with 72.36% for humans; the authors highlighted GUI grounding and operational knowledge as major difficulties. Those numbers describe that evaluation and model cohort, not a present-day leaderboard.[2]

Agent-SafetyBench evaluated 16 agent systems on 2,000 cases across 349 interaction environments; none scored above 60% on its safety metric. The authors identify robustness and risk awareness as central weaknesses, and caution that defense prompts alone are insufficient.[3]

A 2026 exploratory interview study with 17 experienced developers finds that oversight is ongoing work: setting boundaries before execution, co-planning, monitoring during execution, and reviewing afterward. The sample is small and focused on software developers, but it gives a concrete account of why "the human is in the loop" can mean a human doing a lot of hidden verification labor.[4]

## The gap I chose

**An agent's completion claim is not evidence that its acceptance criteria passed.** Benchmarks score outcomes, while real workflows need inspectable, durable evidence attached to explicit criteria. A second LLM saying "looks good" is not independent verification; nor does a text log prove its own authenticity.

## Prototype: Proofrail

Proofrail began as a literal-text evidence gate. That was too easy to fool: a saved file containing "OK" could be fabricated. The current command-check path instead requires an explicit command (stored as an argv list, not shell text); `show` displays the plan and its SHA-256, and `run --approve-hash …` only executes if the bytes still match the inspected hash. It launches with `shell=False` and a timeout, captures stdout/stderr and the process exit code, and blocks completion unless that captured run exited successfully. Its output digest catches accidental edits to captured output, and the plan hash catches plan changes after review. I tested an exit code of 3 even when the process prints "OK"; a timed-out process, modified capture, and a plan edited after approval are all blocked.

This remains a prototype, not a security boundary. Copying a hash is a review workflow, not proof of informed consent. It does not sandbox the validator or stop a compromised agent from changing the plan before review, weakening tests, or manipulating records. A real deployment needs a protected/immutable plan, trusted test runner, isolated execution, and adversarial tests. It does not solve general agent autonomy; it tests whether some routine verification work can be made machine-checkable, leaving humans to define goals, choose trusted checks, and handle ambiguous or high-impact judgment.

## Sources

[1] https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks — METR — Measuring AI Ability to Complete Long Software Tasks
[2] https://arxiv.org/abs/2404.07972 — OSWorld: Real computer environments benchmark
[3] https://arxiv.org/abs/2412.14470 — Agent-SafetyBench: Evaluating LLM-agent safety
[4] https://arxiv.org/html/2606.05391v1 — Human oversight of agentic systems in practice
