"""Let the model save and look up long-term facts. Saved facts are also put in the system prompt."""
from ..store import store
from . import integer, string, tool


@tool("Save a lasting fact about the user or their preferences, e.g. 'User's dog is called Rex'. "
      "Use whenever the user says 'remember' or shares something worth keeping.",
      {"fact": string("The fact, as a short standalone sentence")})
def remember(fact: str) -> str:
    return f"Saved fact #{store.add_fact(fact)}"


@tool("Search saved facts and past conversations.",
      {"query": string("Keywords to look for")})
def recall(query: str) -> str:
    facts = store.search_facts(query)
    log = store.search_log(query, 6)
    parts = [f"#{i}: {t}" for i, t in facts]
    parts += [f"[{ts[:16]}] {role}: {c[:200]}" for ts, role, c in log]
    return "\n".join(parts) or "Nothing found."


@tool("Delete a saved fact by its number.", {"fact_id": integer("Fact number from recall")},
      confirm=lambda a: f"Forget fact #{a.get('fact_id')}?")
def forget(fact_id: int) -> str:
    return "Forgotten." if store.delete_fact(int(fact_id)) else f"No fact #{fact_id}"
