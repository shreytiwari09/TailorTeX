import pytest

from tailortex.llm.client import Usage
from tailortex.llm.schemas import Plan
from tailortex.types import JobAnalysis


class MockLLM:
    """Returns scripted replies: one JobAnalysis, then Plans in order (the last one repeats)."""

    provider = "mock"
    model = "mock-1"
    notify = None  # set by the streaming endpoint, like the real client
    switched_from = None

    def __init__(self, analysis: dict, plans: list[dict]):
        self.analysis = analysis
        self.plans = plans
        self.plan_calls = 0
        self.usage = Usage()
        self.prompts: list[tuple[str, str]] = []

    async def complete(self, system, user, schema):
        self.usage.add(Usage(100, 50, 1))
        self.prompts.append((system, user))
        if schema is JobAnalysis:
            return JobAnalysis.model_validate(self.analysis)
        assert schema is Plan
        plan = self.plans[min(self.plan_calls, len(self.plans) - 1)]
        self.plan_calls += 1
        return Plan.model_validate(plan)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORTEX_DATA_DIR", str(tmp_path / "data"))
