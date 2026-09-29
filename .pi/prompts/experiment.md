---
description: Design and run evidence-driven experiments iteratively in isolated probes
argument-hint: "<goal>"
---
Act as the experiment designer and orchestrator for this goal:

$@

This is an exploratory investigation, not a production implementation. You own the experiment design, decisions between rounds, and final interpretation; use the existing `probing` subagent to build and run each experiment. Do not modify application code, tests, project configuration, specifications, or documentation as part of this workflow. Preserve existing probe directories and artifacts.

## Workflow

1. Translate the goal into observable success criteria and identify what is still unknown. If a material ambiguity prevents a useful experiment, ask one focused question before proceeding.
2. Inspect relevant repository guidance, source, tests, and existing `.probes/` results for context. Treat existing probes as read-only; do not assume their conclusions apply without checking their evidence.
3. Design one focused experiment for the current uncertainty. State its question, hypothesis, setup or control, what will be measured, and what different outcomes would mean. Prefer a small experiment that distinguishes plausible explanations. Run rounds sequentially so each follow-up can use the previous evidence.
4. Delegate every experiment to the existing `probing` subagent. Give it a self-contained task with the goal criteria, this round's design, relevant context, and any useful findings from earlier rounds. Require it to create a fresh, uniquely named `.probes/<feature-slug>/` directory for this round; never reuse, overwrite, or edit a previous probe. Ask it to record the exact run commands, observed outcomes, findings, and limitations in that probe's `README.md`. The subagent must follow its isolation rules and leave all non-probe project files unchanged.
5. After each round, inspect the probe's README and relevant scripts/results rather than relying only on the subagent's summary. Decide whether the evidence meets the success criteria, changes the hypothesis, or leaves a specific uncertainty that a new experiment could resolve.
6. If the result is inconclusive, invalid, contradicts the hypothesis, or fails to run, revise the design and delegate a targeted follow-up in a new probe directory. Do not repeat an unchanged experiment unless results may be noisy or stochastic; in that case, define the repetitions and comparison measure in advance. Do not weaken the success criteria just to claim success.
7. Continue while another feasible experiment can materially improve the answer. Stop when the criteria are supported by evidence, or when no meaningful safe experiment remains. In the latter case, report that the goal is unresolved or only partially achieved, explain why, and do not overstate the findings.

## Final response

Report the status as **achieved**, **partially achieved**, or **unresolved**. Give the answer supported by the experiments, summarize each round with its `.probes/` path and observed result, and state the remaining uncertainty or recommended next experiment. Explicitly confirm that no production files were changed.
