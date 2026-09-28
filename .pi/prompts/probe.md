---
description: Experiment with a feature idea in an isolated probe
argument-hint: "<feature request>"
---
Use the `probing` subagent to experiment with and implement a probe for this feature request:

$@

Delegate the experiment to the subagent; do not implement the feature in the application yourself. The subagent must put all experiment files in a new, feature-named subdirectory under `.probes/` and must not change production files. After it finishes, summarize the probe path, how to run it, what it demonstrated, and what remains uncertain.