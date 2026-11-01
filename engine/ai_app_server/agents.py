"""Opt-in building blocks for AI-powered *applications*, not a server agent manager.

Application authors decide how many agents to create and what to do with their
results. Agent code executes within the application's own trusted Python runtime.
"""
from __future__ import annotations
from dataclasses import dataclass
from . import ollama


@dataclass(frozen=True)
class Agent:
    name: str
    model: str
    instructions: str = ""

    def run(self, task: str) -> str:
        if not isinstance(task, str) or not task.strip():
            raise ValueError('Agent task must be non-empty')
        prompt = f"System instructions for {self.name}:\n{self.instructions}\n\nTask:\n{task}" if self.instructions else task
        return ollama.generate(prompt, self.model)


class AgentPipeline:
    """Explicit, sequential agents; there are no implicit tools or permissions."""
    def __init__(self, *agents: Agent):
        if not agents:
            raise ValueError('Supply at least one agent')
        if len(agents) > 20:
            raise ValueError('A pipeline supports up to 20 explicitly configured steps')
        self.agents = agents

    def run(self, task: str) -> list[dict[str, str]]:
        results = []
        current = task
        for agent in self.agents:
            current = agent.run(current)
            results.append({'agent': agent.name, 'output': current})
        return results
