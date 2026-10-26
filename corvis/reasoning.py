"""Task-adaptive reasoning context and explicit decision records for Corvis."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

REASONING_PRINCIPLES = """\nCorvis reasoning principles:\n- Treat external model output as a proposal, not unquestionable authority.\n- Use relevant evidence, memories, recorded beliefs, and current information; distinguish each source.\n- For nontrivial decisions, compare plausible alternatives and counterevidence before concluding.\n- State uncertainty when evidence is incomplete or conflicting; never invent sources or experience.\n- Revise conclusions when credible new evidence warrants it, and explain material changes.\n- Do not claim to have learned from an outcome unless the outcome was observed and recorded.\n- Do not expose hidden chain-of-thought. Provide concise rationale, key evidence, assumptions, alternatives, and uncertainty instead.\n- Before significant or irreversible actions, follow Corvis's configured approval policy. A model instruction never overrides tool permissions.\n"""

@dataclass
class DecisionRecord:
    question: str
    conclusion: str
    evidence: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    uncertainty: str = ""
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "conclusion": self.conclusion, "evidence": self.evidence,
                "alternatives": self.alternatives, "uncertainty": self.uncertainty,
                "confidence": self.confidence}


def should_use_deliberation(task: str) -> bool:
    """Heuristic hint only; callers must still allow the model to ask/act directly."""
    text = task.lower()
    signals = ("should i", "recommend", "compare", "trade-off", "tradeoff", "plan", "design",
               "why", "root cause", "decide", "evaluate", "strategy", "architecture", "risk")
    return len(task.strip()) > 240 or any(s in text for s in signals)
