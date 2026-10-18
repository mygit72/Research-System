import uuid

import app.services.llm as llm_service
from app.core.config import Settings
from app.services.llm import UserModel, get_coding_llm, resolve_code_model


def test_code_requests_use_the_dedicated_local_model(monkeypatch) -> None:
    monkeypatch.setattr(llm_service, "active_model", lambda: None)
    settings = Settings(
        llm_provider="ollama",
        llm_model="qwen2.5-coder:7b",
        ollama_base_url="http://127.0.0.1:11434",
        code_llm_model="qwen2.5-coder:14b",
    )

    llm = get_coding_llm(settings)

    assert llm.model_id == "qwen2.5-coder:14b"
    assert resolve_code_model(settings) == "qwen2.5-coder:14b"


def test_local_user_model_uses_its_own_ollama_server(monkeypatch) -> None:
    user = UserModel(
        user_id=uuid.uuid4(),
        preset="ollama",
        provider="ollama",
        model="qwen2.5-coder:7b",
        base_url="http://localhost:11434",
        encrypted_key=None,
        key_hint="",
    )
    monkeypatch.setattr(llm_service, "active_model", lambda: user)
    settings = Settings(
        code_llm_model="qwen2.5-coder:14b",
        ollama_base_url="http://127.0.0.1:11434",
        free_tier=True,
    )

    llm = get_coding_llm(settings)

    assert llm.model_id == "qwen2.5-coder:14b"
    assert llm.inner.base_url == "http://localhost:11434"


def test_dedicated_coder_does_not_override_a_users_other_ollama_server(monkeypatch) -> None:
    user = UserModel(
        user_id=uuid.uuid4(),
        preset="ollama",
        provider="ollama",
        model="qwen2.5-coder:7b",
        base_url="http://192.168.1.50:11434",
        encrypted_key=None,
        key_hint="",
    )
    monkeypatch.setattr(llm_service, "active_model", lambda: user)

    assert resolve_code_model(
        Settings(
            code_llm_model="qwen2.5-coder:14b",
            ollama_base_url="http://127.0.0.1:11434",
        )
    ) == "qwen2.5-coder:7b"


def test_hosted_user_model_is_not_silently_replaced(monkeypatch) -> None:
    user = UserModel(
        user_id=uuid.uuid4(),
        preset="openai",
        provider="openai",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        encrypted_key="encrypted",
        key_hint="…1234",
    )
    sentinel = object()
    monkeypatch.setattr(llm_service, "active_model", lambda: user)
    monkeypatch.setattr(llm_service, "get_llm", lambda _settings, _usage=None: sentinel)

    assert get_coding_llm(Settings(code_llm_model="qwen2.5-coder:14b")) is sentinel
    assert resolve_code_model(Settings(code_llm_model="qwen2.5-coder:14b")) == "gpt-4o-mini"
