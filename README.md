# TransLinkInsight: A Policy & Patronage Agent for South East Queensland

An MCP-based AI agent (built on the SMAC starter kit) that answers
questions about how public transport **service quality** relates to **patronage**
in South East Queensland, using open TransLink performance data.

> **Scope note:** This tool reports changes and correlations only.
> It does not claim causal effects (no control group, no confounder adjustment).


## Demo

Example questions:
- "How did Citytrain punctuality change from 2023-12 to 2024-07?"
- "Is there a relationship between SEQ patronage and on-time running?"

## Features

Three MCP tools (policy domain):

| Tool | Purpose |
|---|---|
| `get_patronage` | Monthly SEQ patronage by mode (bus / citytrain / tram) |
| `get_mode_trend` | Change in patronage or punctuality for a mode over a window |
| `analyze_service_relationship` | Pearson r (raw and first-differenced) between two network-level signals: patronage, on-time running, complaint rate, customer experience |

Design choices worth noting:
- Reports both raw-level and first-differenced correlations, to avoid spurious results from shared trends
- Returns sample size and significance flag, plus fixed caveats in every response
- Declines out-of-range or unsupported requests with the standard `out_of_scope` envelope


## Architecture

```
User question → Router (LLM) → MCP server (policy) → tools → data.py → open data CSVs
```


## Getting Started

**Prerequisites:** Docker, Python 3.10+ 

```bash
git clone <repo-url>
cd <repo>
docker compose -f docker/compose.yml up -d
```

Run the evaluation suite:

```bash
docker compose -f docker/compose.yml exec policy \
  python src/eval/run_eval.py \
  --url http://127.0.0.1:8002/mcp \
  --tasks src/eval/tasks.policy.v1.json
```

## Evaluation

16 test cases covering tool selection, tool return values, malformed input and
out-of-range handling. Expected values were computed by an independent script
(`verify_ground_truth.py`) that does not import the project code; see
`GROUND_TRUTH_RECORD.md` for the traceability record.

## Key Findings

- Citytrain on-time running vs complaint rate: r ≈ -0.56 (raw), -0.53 (differenced), the most consistent signal
- Punctuality vs patronage: no significant relationship in either form
- Known limitations: ~30 months of data, no causal identification, [others]

## Project Structure

```
src/
  agents/policy.py     # tool definitions
  data.py              # data loading and cleaning
  eval/                # eval runner and task cases
docker/compose.yml
```

## License & Acknowledgements

Data: Queensland Government, CC-BY 3.0. Built for REIT7820, The University of Queensland.

## Evaluate

Each case in `src/eval/tasks.policy.json` holds a prompt, the tools you expect
called with their arguments, and the output you expect back:

```json
{
  "prompt": "How many trips were taken in the second half of 2024?",
  "tools": [
    {"name": "get_patronage", "input": {"start_month": "2024-07", "end_month": "2024-12"}}
  ],
  "output": {"total_trips": 96472138}
}
```

Numbers must match exactly. Text matches if your string appears anywhere in the
response. Derive every expected value from the dataset yourself, never from your
agent's output. Include a question you should decline and one malformed input.

```bash
docker compose exec policy python eval/run_eval.py --tasks eval/tasks.policy.json
```

W&B logging is required: every run is logged to your W&B project, so runs sit
side by side. Each run first checks your Claude API key with one small call and
opens the W&B run. Then it runs the cases and logs them. If either key is
missing or rejected, it stops before the first case.

## Ask your agent anything

Write a question in `prompt.txt`, then:

```bash
docker compose exec -T policy python ask.py < prompt.txt
```

A model sees only your tools' names and descriptions, picks which to call, and
answers from what they return, which is how the Orchestrator will use your agent.
Each step is printed in order: the tool chosen and why, its arguments, what it
returned, and then the answer. Add `--model claude-sonnet-5` after `ask.py` to
change the model doing the choosing; your agent's own model stays the same.

The question, the tool calls and the answer are printed in colour. To turn
colour off, for example when saving the output to a file, add `-e NO_COLOR=1`
after `exec`.

## Handshake test

The conformance check from the spec, and a hurdle for the Showcase. It connects
to your agent the way the Orchestrator does and runs six checks. Put the
`smac-handshake-test/` folder in the repository root, then:

```bash
docker compose run --rm handshake
```