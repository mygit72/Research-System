"""Local cross-encoder rerankers (sentence-transformers `CrossEncoder`).

Works with MS MARCO cross-encoders (fast on CPU) and BGE rerankers (more accurate,
best on a GPU). Raw logits are mapped through a sigmoid so scores are in [0, 1]
whatever the model's default activation.
"""

from __future__ import annotations

from typing import Any

from app.services.models.manager import ModelManager, resolve_device, resolve_dtype
from app.services.reranking.base import RerankError, sigmoid


class CrossEncoderReranker:
    is_remote = False

    def __init__(
        self,
        model_name: str,
        manager: ModelManager,
        device: str = "auto",
        dtype: str = "auto",
        batch_size: int = 16,
        max_length: int = 512,
    ) -> None:
        self.model_id = model_name
        self.manager = manager
        self.device = resolve_device(device)
        self.dtype = resolve_dtype(dtype, self.device)
        self.batch_size = batch_size
        self.max_length = max_length

    def _model(self) -> Any:
        def load() -> Any:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover - depends on install
                raise RerankError(
                    "Local reranking models aren't installed on this server.",
                    detail="pip install -e '.[ml]'",
                ) from exc
            try:
                model = CrossEncoder(self.model_id, device=self.device, max_length=self.max_length)
            except Exception as exc:
                raise RerankError(
                    f"The reranking model “{self.model_id}” couldn't be loaded.",
                    detail=repr(exc),
                ) from exc
            if self.dtype == "float16":
                model.model.half()
            return model

        return self.manager.get(f"rerank:{self.model_id}:{self.device}:{self.dtype}", load)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        try:
            import torch

            logits = self._model().predict(
                [(query, passage) for passage in passages],
                batch_size=self.batch_size,
                activation_fn=torch.nn.Identity(),
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except RerankError:
            raise
        except Exception as exc:
            raise RerankError("Reranking failed.", detail=repr(exc)) from exc
        return [sigmoid(float(x)) for x in logits.reshape(-1)]
