"""Domain core: entities, rules and capability port contracts.

`happy.core` imports nothing from the other modules of the system. Everything
here is pure: no I/O, no network, no database, no LLM. That is what allows the
domain rules — including the data-usage policy in `usage_policy` — to be tested
without any external dependency.
"""
