from __future__ import annotations

import pytest

from greenhome.llm.budget import Deadline
from greenhome.llm.fake import ScriptedClient
from greenhome.llm.memory_parser import parse_memory
from greenhome.llm.settings import load_llm_settings

SETTINGS = load_llm_settings(env={})


def _kinds(message: str, **kw) -> list[dict]:
    return [e.payload.model_dump() for e in parse_memory(message, **kw)]


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "We installed loft insulation last year and we don't want a heat pump",
            [
                {"kind": "completed_retrofit", "retrofit": "loft_insulation", "completed_on": None},
                {"kind": "exclude", "retrofit": "air_source_heat_pump"},
            ],
        ),
        (
            "We had cavity wall insulation fitted in March 2023",
            [{"kind": "completed_retrofit", "retrofit": "cavity_wall_insulation", "completed_on": "2023-03"}],
        ),
        (
            "we got solar panels in 2024-06",
            [{"kind": "completed_retrofit", "retrofit": "solar_pv", "completed_on": "2024-06"}],
        ),
        (
            "We already have solar panels",
            [{"kind": "completed_retrofit", "retrofit": "solar_pv", "completed_on": None}],
        ),
        ("Our budget is £10,000", [{"kind": "budget", "max_budget_gbp": 10000.0}]),
        ("we can spend up to £5k", [{"kind": "budget", "max_budget_gbp": 5000.0}]),
        ("we care most about carbon", [{"kind": "preference", "priority": "carbon"}]),
        ("money is our priority", [{"kind": "preference", "priority": "bills"}]),
        (
            "We said no to solar last time",
            [{"kind": "response", "retrofit": "solar_pv", "response": "declined"}],
        ),
        (
            "I can't have a heat pump, no outdoor space",
            [{"kind": "exclude", "retrofit": "air_source_heat_pump"}],
        ),
        (
            "We’re not interested in double glazing or solar",
            [{"kind": "exclude", "retrofit": "double_glazing"}, {"kind": "exclude", "retrofit": "solar_pv"}],
        ),
        ("what if we had a heat pump", []),
        ("hello", []),
        ("our budget is tight", []),  # no amount → nothing invented
    ],
)
def test_rules(message, expected) -> None:
    assert _kinds(message) == expected


def test_llm_fallback_drops_invented_budgets_and_dates() -> None:
    reply = (
        '{"events": [{"kind": "budget", "max_budget_gbp": 9000}, '
        '{"kind": "exclude", "retrofit": "solar_pv"}, '
        '{"kind": "completed_retrofit", "retrofit": "loft_insulation", "completed_on": "2020-01"}, '
        '{"kind": "exclude", "retrofit": "teleporter"}]}'
    )
    events = _kinds(
        "loft is sorted, panels are a no-go",
        llm=ScriptedClient([reply]),
        deadline=Deadline(25),
        settings=SETTINGS,
    )
    assert events == [
        {"kind": "exclude", "retrofit": "solar_pv"},
        {"kind": "completed_retrofit", "retrofit": "loft_insulation", "completed_on": None},
    ]


@pytest.mark.parametrize("reply", ["nope", '{"events": "x"}', '{"other": []}'])
def test_bad_llm_replies_give_nothing(reply) -> None:
    assert (
        _kinds("loft is sorted", llm=ScriptedClient([reply]), deadline=Deadline(25), settings=SETTINGS) == []
    )
