"""Tests for the minimal DeepSeek Agent tool loop."""

import sys
from types import SimpleNamespace

import pytest
from reposentinel.agent import review_agent
from reposentinel.agent.review_agent import ReviewAgent
from reposentinel.tools.repository_tools import RepositoryTools


class FakeCompletions:
    """Return predetermined messages and record completion requests."""

    def __init__(self, messages):
        """Initialize configured messages and a request history."""
        self.messages = iter(messages)
        self.requests = []

    def create(self, **request):
        """Record one request and return its configured response."""
        request["messages"] = list(request["messages"])
        self.requests.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.messages))])


class FakeClient:
    """Provide the nested OpenAI-compatible chat completion surface."""

    def __init__(self, messages):
        """Initialize the fake completion surface."""
        self.completions = FakeCompletions(messages)
        self.chat = SimpleNamespace(completions=self.completions)


def _tool_call(name: str, arguments: str):
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _message(content: str | None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def test_agent_returns_tool_results_to_model(fixture_repo):
    """Complete the model-to-tool-to-model loop with an injected client."""
    client = FakeClient(
        [
            _message(None, [_tool_call("get_project_summary", "{}")]),
            _message("The repository profile is available."),
        ]
    )
    trace = []
    agent = ReviewAgent(
        RepositoryTools(fixture_repo),
        client=client,
        tool_names=("get_project_summary",),
        trace=trace.append,
    )

    review = agent.review("Inspect the repository.", require_initial_tool=True)

    assert review == "The repository profile is available."
    assert len(client.completions.requests) == 2
    assert client.completions.requests[0]["tool_choice"] == "required"
    assert client.completions.requests[1]["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    tool_message = client.completions.requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert '"project_name":' in tool_message["content"]
    assert trace[0] == "[Agent] get_project_summary({})"
    assert trace[1].startswith("[Tool] {")


def test_agent_returns_invalid_tool_arguments_as_tool_evidence(fixture_repo):
    """Return validation errors to the model instead of executing invalid calls."""
    client = FakeClient(
        [
            _message(None, [_tool_call("read_file", '{"path": "../secret.txt"}')]),
            _message("I could not read that file."),
        ]
    )
    agent = ReviewAgent(RepositoryTools(fixture_repo), client=client)

    review = agent.review("Inspect the repository.")

    assert review == "I could not read that file."
    tool_message = client.completions.requests[1]["messages"][-1]
    assert "escapes the repository root" in tool_message["content"]


def test_agent_requires_repository_tools_for_review():
    """Keep smoke tests separate from repository exploration."""
    agent = ReviewAgent(None, client=FakeClient([_message("hello")]))

    with pytest.raises(RuntimeError, match="Repository tools"):
        agent.review()


def test_agent_smoke_test_does_not_send_tools():
    """Verify the API-only smoke path has no repository tool dependency."""
    client = FakeClient([_message("hello")])
    agent = ReviewAgent(None, client=client)

    assert agent.run_smoke_test() == "hello"
    assert "tools" not in client.completions.requests[0]


@pytest.mark.parametrize("model", ["deepseek-v4-pro", "deepseek-v4-flash"])
def test_agent_supports_deepseek_model_switching(model):
    """Send the caller-selected DeepSeek model to the compatible client."""
    client = FakeClient([_message("hello")])
    agent = ReviewAgent(None, client=client, model=model)

    agent.run_smoke_test()

    assert client.completions.requests[0]["model"] == model


def test_agent_requires_runtime_api_key(monkeypatch):
    """Require an API key when a real client is requested."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        ReviewAgent(None)


def test_agent_cli_rejects_output_inside_inspected_repository(
    fixture_repo, monkeypatch
):
    """Keep generated reviews outside the repository under inspection."""
    output = fixture_repo / "review.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_agent",
            str(fixture_repo),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as error:
        review_agent.main()

    assert error.value.code == 2
    assert not output.exists()
