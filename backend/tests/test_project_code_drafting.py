from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.analysis.digests import SourceBook
from app.services.projects import draft_code
from app.services.projects.draft_code import (
    _model_validation_error,
    _strip_fences,
    _valid,
    _validation_error,
)


def test_draft_parser_accepts_fenced_methods_with_or_without_member_indentation() -> None:
    for indentation in ("", "    "):
        reply = (
            "```python\n"
            f"{indentation}def rank(self, example, seed):\n"
            f"{indentation}    return [0]\n\n"
            f"{indentation}def answer(self, example, seed):\n"
            f"{indentation}    return example['passages'][0]\n"
            "```"
        )

        code = _strip_fences(reply)

        assert _valid(code)
        assert code.startswith("def rank")


def test_draft_parser_rejects_todo_only_methods() -> None:
    code = """\
def rank(self, example, seed):
    # TODO: implement
    pass

def answer(self, example, seed):
    raise NotImplementedError('TODO')
"""

    assert not _valid(code)


def test_comment_only_methods_explain_the_interface_mismatch() -> None:
    reply = """```python
    def rank(self, example, seed):
        # TODO: implement ranking

    def answer(self, example, seed):
        # TODO: implement answering
```"""
    error = _validation_error(_strip_fences(reply))

    assert error is not None
    assert "TODO-only" in error
    assert "retrieval" in error


def test_draft_parser_rejects_prose_and_incomplete_methods() -> None:
    assert not _valid("Here is the code:\ndef rank(self, example, seed):\n    return []")
    assert not _valid("def rank(self, example, seed):\n    return []")


def test_model_parser_extracts_code_when_qwen_wraps_it_in_prose_and_fences() -> None:
    reply = "Here is the implementation:\n```python\nclass ResearchModel:\n    pass\n```\nDone."
    assert _strip_fences(reply) == "class ResearchModel:\n    pass"


def test_model_draft_accepts_documented_code_and_rejects_empty_classes() -> None:
    assert _model_validation_error(
        "class ResearchModel:\n    def forward(self, inputs):\n        return inputs\n"
    ) is None
    assert _model_validation_error("class ResearchModel:\n    pass\n")
    assert _model_validation_error(
        "class ResearchModel:\n    def forward(self, inputs):\n        raise NotImplementedError\n"
    )
    assert _model_validation_error("Here is your model")


def test_model_draft_rejects_unsourced_architecture_numbers() -> None:
    code = "class ResearchModel:\n    def forward(self, x):\n        return x + 512\n"
    assert "unsupported numeric value 512" in (_model_validation_error(code) or "")
    assert _model_validation_error(code, "The paper uses an embedding dimension of 512.") is None


def test_model_draft_allows_missing_inline_citations_but_rejects_invented_sources() -> None:
    supported = """# Paper evidence: [1]
class ResearchModel:
    def forward(self, inputs):
        return inputs
"""
    assert _model_validation_error(supported, allowed_sources=[1]) is None

    uncited = supported.replace("# Paper evidence: [1]\n", "")
    assert _model_validation_error(uncited, allowed_sources=[1]) is None

    invented = supported.replace("[1]", "[2]")
    assert "not supplied: 2" in (
        _model_validation_error(invented, allowed_sources=[1]) or ""
    )


async def test_model_draft_repairs_an_unsupported_numeric_default(monkeypatch: pytest.MonkeyPatch) -> None:
    unsupported = "class ResearchModel:\n    def forward(self, inputs):\n        return inputs + 512\n"
    repaired = "class ResearchModel:\n    def forward(self, inputs):\n        return inputs\n"

    class Writer:
        model = "qwen-test"
        params = None

        def __init__(self) -> None:
            self.replies = [unsupported, repaired]
            self.messages = []

        async def generate(self, messages, label):
            self.messages.append((messages, label))
            return self.replies.pop(0)

    writer = Writer()

    async def evidence(_session_factory, _settings, _project, _query, book, max_passages):
        book.add(
            {
                "chunk_id": "chunk-1",
                "document": {"id": "paper-1", "title": "Attention Is All You Need", "year": 2017},
                "section_title": "Scaled Dot-Product Attention",
                "page_start": 4,
                "quote": "Attention uses scaled dot-product scores and a softmax over values.",
            }
        )
        return [1]

    monkeypatch.setattr(draft_code, "_evidence", evidence)
    monkeypatch.setattr(draft_code, "_writer", lambda _settings, _book: writer)
    result = await draft_code._draft_model(
        object(),
        SimpleNamespace(summary_max_tokens=700, llm_temperature=0.1),
        SimpleNamespace(
            idea="Study attention",
            question="How does scaled attention behave?",
            hypothesis="Scaling stabilizes scores.",
            title="Attention study",
        ),
    )

    assert result["status"] == "drafted"
    assert "return inputs" in result["code"]
    assert len(writer.messages) == 2
    assert "unsupported numeric value 512" in writer.messages[1][0][1].content
