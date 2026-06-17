"""
Trace Logger -- Records all agent interactions for visualization.

Captures every message passed between agents (orchestrator, planner, installer,
explorer) including what data was sent, what was received, timing, and decisions.

Usage:
    from trace_logger import tracer
    
    tracer.log_agent_start("planner")
    tracer.log_agent_input("planner", {"goal": "...", "pdf_path": "..."})
    tracer.log_agent_output("planner", {"tasks": [...], "findings": [...]})
    tracer.log_agent_end("planner")
    
    tracer.log_tool_call("explorer", "submit_task", {"name": "run_lammps"}, result)
    
    # Get full trace
    trace = tracer.get_trace()
    
    # Save to file
    tracer.save("trace.json")
"""

import json
import time
from datetime import datetime
from typing import Any, Optional


class TraceLogger:
    def __init__(self):
        self.events: list[dict] = []
        self.start_time: float = time.time()
        self._agent_starts: dict[str, float] = {}

    def _elapsed(self) -> float:
        return round(time.time() - self.start_time, 2)

    def log_agent_start(self, agent_name: str, metadata: Optional[dict] = None):
        """Record that an agent started executing."""
        self._agent_starts[agent_name] = time.time()
        event = {
            "type": "agent_start",
            "agent": agent_name,
            "elapsed_s": self._elapsed(),
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            event["metadata"] = metadata
        self.events.append(event)

    def log_agent_input(self, agent_name: str, data: dict):
        """Record what data an agent received as input."""
        # Summarize large fields to keep trace readable
        summarized = {}
        for key, val in data.items():
            if isinstance(val, list) and len(val) > 5:
                summarized[key] = f"[{len(val)} items]"
            elif isinstance(val, str) and len(val) > 200:
                summarized[key] = val[:200] + "..."
            elif isinstance(val, dict) and len(str(val)) > 200:
                summarized[key] = f"{{dict with {len(val)} keys}}"
            else:
                summarized[key] = val

        self.events.append({
            "type": "agent_input",
            "agent": agent_name,
            "data": summarized,
            "elapsed_s": self._elapsed(),
        })

    def log_agent_output(self, agent_name: str, data: dict):
        """Record what data an agent produced as output."""
        summarized = {}
        for key, val in data.items():
            if isinstance(val, list) and len(val) > 5:
                summarized[key] = f"[{len(val)} items]"
            elif isinstance(val, str) and len(val) > 200:
                summarized[key] = val[:200] + "..."
            elif isinstance(val, dict) and len(str(val)) > 200:
                summarized[key] = f"{{dict with {len(val)} keys}}"
            else:
                summarized[key] = val

        self.events.append({
            "type": "agent_output",
            "agent": agent_name,
            "data": summarized,
            "elapsed_s": self._elapsed(),
        })

    def log_agent_end(self, agent_name: str):
        """Record that an agent finished executing."""
        duration = 0
        if agent_name in self._agent_starts:
            duration = round(time.time() - self._agent_starts[agent_name], 2)

        self.events.append({
            "type": "agent_end",
            "agent": agent_name,
            "duration_s": duration,
            "elapsed_s": self._elapsed(),
        })

    def log_routing(self, from_agent: str, to_agent: str, reasoning: str, feedback: str = ""):
        """Record an orchestrator routing decision."""
        self.events.append({
            "type": "routing",
            "from": from_agent,
            "to": to_agent,
            "reasoning": reasoning[:300],
            "feedback": feedback[:200] if feedback else "",
            "elapsed_s": self._elapsed(),
        })

    def log_tool_call(self, agent_name: str, tool_name: str, args: dict,
                      result: str, succeeded: bool, duration_s: float = 0):
        """Record a tool call made by an agent."""
        # Summarize args
        summarized_args = {}
        for key, val in args.items():
            if isinstance(val, str) and len(val) > 100:
                summarized_args[key] = val[:100] + "..."
            else:
                summarized_args[key] = val

        # Summarize result
        result_summary = result[:300] if isinstance(result, str) else str(result)[:300]

        self.events.append({
            "type": "tool_call",
            "agent": agent_name,
            "tool": tool_name,
            "args": summarized_args,
            "result_summary": result_summary,
            "succeeded": succeeded,
            "duration_s": duration_s,
            "elapsed_s": self._elapsed(),
        })

    def log_token_usage(self, agent_name: str, input_tokens: int, output_tokens: int,
                         total_tokens: int = 0, model: str = ""):
        """Record token consumption for a single LLM call made by an agent."""
        if not total_tokens:
            total_tokens = input_tokens + output_tokens
        self.events.append({
            "type": "token_usage",
            "agent": agent_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "model": model,
            "elapsed_s": self._elapsed(),
        })

    def log_message(self, from_agent: str, to_agent: str, message: str):
        """Record a message passed between agents via state."""
        self.events.append({
            "type": "message",
            "from": from_agent,
            "to": to_agent,
            "message": message[:300],
            "elapsed_s": self._elapsed(),
        })

    def get_trace(self) -> list[dict]:
        """Get the full trace as a list of events."""
        return self.events

    def get_summary(self) -> dict:
        """Get a summary of the trace."""
        agents_seen = set()
        tool_calls = 0
        tool_successes = 0
        routings = []
        total_input_tokens = 0
        total_output_tokens = 0
        tokens_by_agent: dict[str, int] = {}

        for event in self.events:
            if event["type"] in ("agent_start", "agent_end"):
                agents_seen.add(event["agent"])
            elif event["type"] == "tool_call":
                tool_calls += 1
                if event.get("succeeded"):
                    tool_successes += 1
            elif event["type"] == "routing":
                routings.append(f"{event['from']} -> {event['to']}")
            elif event["type"] == "token_usage":
                total_input_tokens += event.get("input_tokens", 0)
                total_output_tokens += event.get("output_tokens", 0)
                tokens_by_agent[event["agent"]] = (
                    tokens_by_agent.get(event["agent"], 0) + event.get("total_tokens", 0)
                )

        return {
            "total_events": len(self.events),
            "total_duration_s": self._elapsed(),
            "agents_involved": sorted(agents_seen),
            "tool_calls": tool_calls,
            "tool_successes": tool_successes,
            "routing_path": routings,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "tokens_by_agent": tokens_by_agent,
        }

    def get_interaction_sequence(self) -> list[dict]:
        """Get a simplified sequence of agent-to-agent interactions for visualization."""
        interactions = []
        for event in self.events:
            if event["type"] == "routing":
                interactions.append({
                    "from": event["from"],
                    "to": event["to"],
                    "elapsed_s": event["elapsed_s"],
                    "reasoning": event["reasoning"],
                })
            elif event["type"] == "agent_end":
                interactions.append({
                    "agent": event["agent"],
                    "action": "completed",
                    "duration_s": event["duration_s"],
                    "elapsed_s": event["elapsed_s"],
                })
            elif event["type"] == "tool_call":
                interactions.append({
                    "agent": event["agent"],
                    "action": f"tool:{event['tool']}",
                    "succeeded": event["succeeded"],
                    "elapsed_s": event["elapsed_s"],
                })
        return interactions

    def save(self, path: str):
        """Save the full trace to a JSON file."""
        with open(path, "w") as f:
            json.dump({
                "trace": self.events,
                "summary": self.get_summary(),
            }, f, indent=2, default=str)

    def reset(self):
        """Clear all trace data."""
        self.events = []
        self.start_time = time.time()
        self._agent_starts = {}


def extract_usage(response: Any) -> Optional[dict]:
    """Pull token counts out of a LangChain chat response.

    Returns {"input_tokens", "output_tokens", "total_tokens"} or None if the
    response carries no usage info.
    """
    # Preferred: AIMessage.usage_metadata (provider-agnostic, normalized keys)
    usage = getattr(response, "usage_metadata", None)
    if usage:
        return {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    # Fallback: response_metadata["token_usage"] (OpenAI-style keys)
    meta = getattr(response, "response_metadata", None) or {}
    tu = meta.get("token_usage") or meta.get("usage")
    if tu:
        return {
            "input_tokens": tu.get("prompt_tokens", 0),
            "output_tokens": tu.get("completion_tokens", 0),
            "total_tokens": tu.get("total_tokens", 0),
        }
    return None


# Global tracer instance
tracer = TraceLogger()
