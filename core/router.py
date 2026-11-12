"""Question understanding: decide which retrieval strategies a question needs."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config

STRATEGIES = {"semantic", "overall_summary", "section", "entity", "relationship", "multi_step"}
STYLES = {"auto", "short", "detailed", "bullets", "summary", "comparison", "steps"}

ROUTER_PROMPT = """TASK: ROUTE
You route a question about ONE uploaded document to the retrieval strategies that can answer it.
Document: "<<TITLE>>" (<<TYPE>>)
Sections: <<SECTIONS>>
Entity types found: <<TYPES>>
Recent conversation: <<HISTORY>>
Question: <<QUESTION>>

Strategies (choose one or several):
- semantic: look up specific facts or explanations in the text
- overall_summary: whole-document summary, main idea, themes, overall purpose, how it ends or concludes
- section: about a specific chapter / section / slide / page / sheet
- entity: about specific entities, or listing entities (characters, skills, organisations, concepts...)
- relationship: how two or more entities are connected
- multi_step: comparisons or questions that need information from several places (give sub_questions)

Return ONLY JSON:
{"strategies": ["..."], "standalone_question": "the question rewritten so it makes sense without the conversation",
 "section_refs": ["e.g. Chapter 12", "page 45"], "entities": ["names mentioned"], "entity_types": ["types to list, e.g. person"],
 "list_all_entities": false, "sub_questions": [], "style": "auto|short|detailed|bullets|summary|comparison|steps"}"""


@dataclass
class Route:
    strategies: list[str] = field(default_factory=lambda: ["semantic"])
    standalone: str = ""
    section_refs: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    entity_types: list[str] = field(default_factory=list)
    list_all: bool = False
    sub_questions: list[str] = field(default_factory=list)
    style: str = "auto"


def heuristic_route(q: str) -> Route:
    low = q.lower()
    r = Route(standalone=q)
    strategies = []
    if re.search(r"summar|overview|main (idea|point)|what is (this|the) (document|book|paper|story)|how does (it|this) (end|conclude)|ending|conclusion|themes?", low):
        strategies.append("overall_summary")
    refs = re.findall(r"(?:chapter|section|part|slide|sheet|page)\s*\w+", low)
    if refs:
        strategies.append("section")
        r.section_refs = refs
    if re.search(r"\b(who are|list (all )?the|all the|characters|people|skills|organi[sz]ations)\b", low):
        strategies.append("entity")
        r.list_all = True
    if re.search(r"relationship|related to|connection between|how .* know", low):
        strategies.append("relationship")
    if re.search(r"compare|difference between|versus|\bvs\b", low):
        strategies.append("multi_step")
        r.sub_questions = [q]
    r.strategies = strategies or ["semantic"]
    return r


def _list(v, n=8):
    return [str(x) for x in v if x][:n] if isinstance(v, list) else []


def route(llm, question: str, doc: dict, sections: list[dict], entity_types: list[str],
          history: list[dict], has_analysis: bool) -> Route:
    if not has_analysis:
        return Route(["semantic"], question)
    ov = doc.get("overview") or {}
    hist = " | ".join(f"{m['role']}: {m['content'][:160]}" for m in history[-4:]) or "none"
    titles = "; ".join(s["title"] for s in sections[:80])
    prompt = (ROUTER_PROMPT.replace("<<TITLE>>", ov.get("title") or doc["name"])
              .replace("<<TYPE>>", ov.get("document_type", "unknown")).replace("<<SECTIONS>>", titles[:2500])
              .replace("<<TYPES>>", ", ".join(entity_types[:12]) or "none").replace("<<HISTORY>>", hist)
              .replace("<<QUESTION>>", question))
    try:
        d = llm.generate_json(prompt, model=config.FAST_MODEL, max_tokens=700)
        if not isinstance(d, dict):
            raise ValueError
    except Exception:  # noqa: BLE001
        return heuristic_route(question)
    strategies = [s for s in _list(d.get("strategies")) if s in STRATEGIES] or ["semantic"]
    style = str(d.get("style", "auto")).lower()
    return Route(strategies, str(d.get("standalone_question") or question), _list(d.get("section_refs"), 3),
                 _list(d.get("entities")), _list(d.get("entity_types")), bool(d.get("list_all_entities")),
                 _list(d.get("sub_questions"), 4), style if style in STYLES else "auto")
