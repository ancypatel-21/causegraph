"""Provider-neutral LLM adapter (spec section 3.1: "LLM via provider-neutral
adapter"). Used by the B2/B4 baselines and, later, the investigator agent.

Per spec section 14 step 18 ("The project must remain useful without any
paid model API"), the default provider is a deterministic, network-free
mock -- every baseline and test works with zero API keys configured. A real
provider is opt-in via CAUSEGRAPH_LLM_PROVIDER=anthropic.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CandidateContext:
    """What a candidate looks like to the LLM. `graph_distance` is None for
    B2 (bounded raw telemetry, no topology hint) and set for B4 (graph
    narrows candidates first)."""

    node_id: str
    node_type: str
    raw_signals: dict[str, float] = field(default_factory=dict)
    graph_distance: int | None = None
    recent_changes: list[str] = field(default_factory=list)


@dataclass
class RankingResult:
    ranked_node_ids: list[str]
    rationale: dict[str, str]
    confidence: float
    provider_name: str
    model_name: str


class LLMProvider(ABC):
    provider_name: str
    model_name: str

    @abstractmethod
    def rank_candidates(
        self, incident_summary: str, candidates: list[CandidateContext]
    ) -> RankingResult: ...


class DeterministicMockProvider(LLMProvider):
    """No network call. A simple, reproducible heuristic standing in for an
    LLM's judgment, so B2/B4 and every test using them run offline and for
    free. Never claim this provider's output as a measurement of real LLM
    quality -- it exists so the pipeline is runnable without a paid API."""

    provider_name = "mock"
    model_name = "deterministic-heuristic-v1"

    def rank_candidates(
        self, incident_summary: str, candidates: list[CandidateContext]
    ) -> RankingResult:
        def candidate_score(c: CandidateContext) -> float:
            signal_peak = max(c.raw_signals.values(), default=0.0)
            change_bonus = 2.0 if c.recent_changes else 0.0
            distance_penalty = 0.1 * c.graph_distance if c.graph_distance is not None else 0.0
            return signal_peak + change_bonus - distance_penalty

        ranked = sorted(candidates, key=candidate_score, reverse=True)
        rationale = {}
        for c in ranked:
            top_signal = max(c.raw_signals.items(), key=lambda kv: kv[1], default=(None, None))
            parts = []
            if top_signal[0] is not None:
                parts.append(f"strongest signal {top_signal[0]}={top_signal[1]:.3g}")
            if c.recent_changes:
                parts.append(f"recent change(s): {'; '.join(c.recent_changes)}")
            if c.graph_distance is not None:
                parts.append(f"graph distance {c.graph_distance}")
            rationale[c.node_id] = "; ".join(parts) if parts else "no notable signal"

        top_score = candidate_score(ranked[0]) if ranked else 0.0
        confidence = min(0.95, 0.4 + 0.1 * top_score) if ranked else 0.0

        return RankingResult(
            ranked_node_ids=[c.node_id for c in ranked],
            rationale=rationale,
            confidence=max(0.0, confidence),
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


class AnthropicProvider(LLMProvider):
    """Real LLM provider. Requires ANTHROPIC_API_KEY. Model is pinned via
    CAUSEGRAPH_LLM_MODEL (spec section 9.4: "Pin model/provider versions
    where possible")."""

    provider_name = "anthropic"

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get(
            "CAUSEGRAPH_LLM_MODEL", "claude-haiku-4-5-20251001"
        )
        import anthropic  # deferred: only required when this provider is selected

        self._client = anthropic.Anthropic()

    def rank_candidates(
        self, incident_summary: str, candidates: list[CandidateContext]
    ) -> RankingResult:
        prompt = self._build_prompt(incident_summary, candidates)
        response = self._client.messages.create(
            model=self.model_name,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        payload = self._extract_json(text)

        valid_ids = {c.node_id for c in candidates}
        ranked = [n for n in payload.get("ranked_node_ids", []) if n in valid_ids]
        missing = [c.node_id for c in candidates if c.node_id not in ranked]
        ranked.extend(missing)  # never silently drop a candidate

        return RankingResult(
            ranked_node_ids=ranked,
            rationale={k: v for k, v in payload.get("rationale", {}).items() if k in valid_ids},
            confidence=float(payload.get("confidence", 0.0)),
            provider_name=self.provider_name,
            model_name=self.model_name,
        )

    @staticmethod
    def _build_prompt(incident_summary: str, candidates: list[CandidateContext]) -> str:
        lines = [
            "You are diagnosing a root cause for a distributed system incident.",
            f"Incident: {incident_summary}",
            "Candidates (rank most-likely-root-cause first):",
        ]
        for c in candidates:
            signals = ", ".join(f"{k}={v:.3g}" for k, v in c.raw_signals.items()) or "none"
            changes = "; ".join(c.recent_changes) or "none"
            distance = "unknown (no topology given)" if c.graph_distance is None else str(c.graph_distance)
            lines.append(
                f"- {c.node_id} (type={c.node_type}, signals=[{signals}], "
                f"recent_changes=[{changes}], graph_distance={distance})"
            )
        lines.append(
            'Respond with ONLY JSON: {"ranked_node_ids": [...], '
            '"rationale": {"<node_id>": "<short reason>"}, "confidence": <0..1>}'
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_json(text: str) -> dict:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"LLM response did not contain JSON: {text!r}")
        return json.loads(text[start : end + 1])


def get_default_provider() -> LLMProvider:
    provider_name = os.environ.get("CAUSEGRAPH_LLM_PROVIDER", "mock")
    if provider_name == "mock":
        return DeterministicMockProvider()
    if provider_name == "anthropic":
        return AnthropicProvider()
    raise ValueError(f"unknown LLM provider '{provider_name}'")
