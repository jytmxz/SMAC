"""
The demo query catalogue.

Each query is a question a person might actually ask, paired with a scripted
plan of tool calls that answers it. The plan is a fallback: when a model is
configured the router chooses the tools itself, and the scripted plan is only
used when no API key is set, or when someone ticks "scripted" to guarantee a
demo runs the same way twice.

An argument written as "$0.location.lat" means "take it from step 0's result",
which is how a query gets geocoded before it is answered.

Every domain includes at least one question the agents should refuse. Watching
an agent decline to answer is the most useful thing an observer can see: it is
the difference between a system that knows its coverage and one that invents.
"""

DOMAINS = [
    {
        "id": "policy",
        "name": "Policy & Patronage",
        "blurb": "Monthly passenger trips by mode, spanning the August 2024 50 cent fare change.",
    },
]

QUERIES = [
    {
        "id": "pol-total",
        "domain": "policy",
        "text": "How many public transport trips were taken in South East Queensland in the second half of 2024?",
        "why": "A total over six months and four modes. The sum is computed from the published rows, never estimated by a model.",
        "plan": [
            {"agent": "policy", "tool": "get_patronage",
             "arguments": {"start_month": "2024-07", "end_month": "2024-12"}},
        ],
    },
    {
        "id": "pol-series",
        "domain": "policy",
        "text": "Show me ferry patronage for the first half of 2025.",
        "why": "A plain series query. The month and mode filters come straight from the question.",
        "plan": [
            {"agent": "policy", "tool": "get_patronage",
             "arguments": {"start_month": "2025-01", "end_month": "2025-06", "mode": "Ferry"}},
        ],
    },
    {
        "id": "pol-fare-change",
        "domain": "policy",
        "text": "Did bus patronage change when 50 cent fares began in August 2024?",
        "why": "The jump from July to August is real and large. Watch the answer report the change without calling it caused by the fare: there is no control group, and the tool says so.",
        "plan": [
            {"agent": "policy", "tool": "get_patronage",
             "arguments": {"start_month": "2024-07", "end_month": "2024-08", "mode": "Bus"}},
        ],
    },
    {
        "id": "pol-out-of-scope",
        "domain": "policy",
        "text": "How many helicopter trips were taken in 2025?",
        "why": "Not a mode in this series. The agent refuses and lists the modes it does hold, which is more useful than an apology.",
        "plan": [
            {"agent": "policy", "tool": "get_patronage",
             "arguments": {"start_month": "2025-01", "end_month": "2025-12", "mode": "Helicopter"}},
        ],
    },
]


def by_id(query_id: str) -> dict | None:
    return next((q for q in QUERIES if q["id"] == query_id), None)
