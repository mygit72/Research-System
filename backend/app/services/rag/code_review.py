"""Small static checks for code drafts returned by the chat model.

These checks don't execute generated code. GPT starter drafts get a few additional checks for
the architecture and next-token objective that distinguish a decoder-only GPT from a generic
Transformer example.
"""

from __future__ import annotations

import ast
import re

_PYTHON_FENCE = re.compile(r"```(?:python|py)\s*\r?\n(.*?)```", re.IGNORECASE | re.DOTALL)
_ANY_FENCE = re.compile(r"```[\w.+-]*\s*\r?\n(.*?)```", re.DOTALL)
_CHAR_VOCAB = re.compile(
    r"(?:sorted\s*\(\s*)?set\s*\(\s*(?:text|data|corpus|raw_text|content|sequence|"
    r"training_text|training_data|dataset|sample_text)\s*\)|"
    r"(?:stoi|itos|char_to_(?:id|idx|index|int|token)|char2(?:idx|id)|token_to_id|encode)",
    re.IGNORECASE,
)


def has_python_code(answer: str) -> bool:
    return bool(_PYTHON_FENCE.search(answer))


def _call_name(call: ast.Call) -> str:
    function = call.func
    return function.attr if isinstance(function, ast.Attribute) else (
        function.id if isinstance(function, ast.Name) else ""
    )


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for child in target.elts for name in _target_names(child)]
    return []


def _number(node: ast.expr | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
    ):
        return -node.operand.value
    return None


def _has_shift(tree: ast.AST, *, left: bool) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        dimensions = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        last = dimensions[-1] if dimensions else None
        if not isinstance(last, ast.Slice):
            continue
        start, stop = _number(last.lower), _number(last.upper)
        if left and start is None and stop == -1:
            return True
        if not left and start == 1 and last.upper is None:
            return True
    return False


def _embedding_targets(tree: ast.AST) -> list[str]:
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "Embedding":
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Assign):
            names.extend(name for target in parent.targets for name in _target_names(target))
        elif isinstance(parent, ast.AnnAssign):
            names.extend(_target_names(parent.target))
    return names


def review_generated_code(answer: str, *, gpt: bool = False) -> list[str]:
    """Return actionable review failures; an empty list means the static checks passed."""
    blocks = _PYTHON_FENCE.findall(answer)
    if not blocks:
        if gpt:
            return ["include one complete Python code block"]
        return (
            []
            if _ANY_FENCE.search(answer)
            else ["include the complete implementation in a code block"]
        )

    trees: list[ast.AST] = []
    for index, code in enumerate(blocks, start=1):
        try:
            trees.append(ast.parse(code))
        except SyntaxError as exc:
            return [f"Python code block {index} has a syntax error on line {exc.lineno}"]
    if not gpt:
        return []

    code = "\n".join(blocks)
    tree = ast.parse(code)
    checks: list[str] = []
    if not any(
        isinstance(node, ast.ClassDef) and "attention" in node.name.casefold()
        for node in ast.walk(tree)
    ):
        checks.append("include a causal self-attention module")

    embeddings = [name.casefold() for name in _embedding_targets(tree)]
    if not any("token" in name or name in {"wte", "tok_emb", "token_emb"} for name in embeddings):
        checks.append("add a learned token embedding")
    if not any(
        "position" in name or name in {"wpe", "pos_emb", "position_emb"}
        for name in embeddings
    ):
        checks.append("add a learned position embedding and use it with the token embedding")

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    call_names = {_call_name(node).casefold() for node in calls}
    attention_classes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and "attention" in node.name.casefold()
    ]
    attention_calls = [
        call
        for cls in attention_classes
        for method in cls.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        for call in ast.walk(method)
        if isinstance(call, ast.Call)
    ]
    attention_call_names = {_call_name(call).casefold() for call in attention_calls}
    projection_names = {
        name.casefold()
        for cls in attention_classes
        for node in ast.walk(cls)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and _call_name(node.value) == "Linear"
        for target in node.targets
        for name in _target_names(target)
    }
    has_separate_qkv = all(
        projection_names & aliases
        for aliases in (
              {"q", "query", "queries", "q_proj", "query_proj", "wq"},
              {"k", "key", "keys", "k_proj", "key_proj", "wk"},
              {"v", "value", "values", "v_proj", "value_proj", "wv"},
        )
    )
    attention_source = "\n".join(ast.unparse(cls) for cls in attention_classes).casefold()
    has_fused_qkv = bool(re.search(r"\b(?:qkv|c_attn)\b", attention_source)) and bool(
        re.search(r"\.(?:chunk|split)\s*\(", attention_source)
    )
    if not (has_separate_qkv or has_fused_qkv):
        checks.append("project separate query, key, and value vectors for self-attention")
    elif has_separate_qkv and not all(
        projection_names & aliases & attention_call_names
        for aliases in (
            {"q", "query", "queries", "q_proj", "query_proj", "wq"},
            {"k", "key", "keys", "k_proj", "key_proj", "wk"},
            {"v", "value", "values", "v_proj", "value_proj", "wv"},
        )
    ):
        checks.append("use the query, key, and value projections in the attention calculation")
    attention_products = sum(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult)
        for cls in attention_classes
        for node in ast.walk(cls)
    ) + sum(
        _call_name(call).casefold() in {"matmul", "bmm", "einsum"}
        for call in attention_calls
    )
    has_scaled_attention = "scaled_dot_product_attention" in attention_call_names
    if not has_scaled_attention and not (
        attention_products >= 2 and "softmax" in attention_call_names
    ):
        checks.append("compute attention scores, normalize them, and combine them with values")
    # Some valid implementations construct the triangular mask in GPT.forward and pass it
    # into the attention module, so allow tril/triu anywhere as long as attention applies it.
    has_mask = bool({"tril", "triu"} & call_names) and "masked_fill" in attention_call_names
    has_causal_sdpa = "scaled_dot_product_attention" in call_names and any(
        keyword.arg == "is_causal" and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "scaled_dot_product_attention"
        for keyword in node.keywords
    )
    if not (has_mask or has_causal_sdpa):
        checks.append("build and apply a causal attention mask")

    embedding_names = {name.casefold() for name in embeddings}
    token_names = {
        name for name in embedding_names
        if "token" in name or name in {"wte", "tok_emb", "token_emb"}
    }
    position_names = {
        name for name in embedding_names
        if "position" in name or name in {"wpe", "pos_emb", "position_emb"}
    }
    summed_embeddings = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != "forward":
            continue
        referenced = {
            child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)
        }
        has_add = any(
            isinstance(child, ast.BinOp) and isinstance(child.op, ast.Add)
            for child in ast.walk(node)
        )
        if token_names & referenced and position_names & referenced and has_add:
            summed_embeddings = True
            break
    if not summed_embeddings:
        checks.append("sum the token and position embeddings in the model forward pass")

    has_norm = "layernorm" in call_names
    linears_by_class: dict[str, list[str]] = {}
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        class_calls = [
            _call_name(node).casefold()
            for node in ast.walk(cls)
            if isinstance(node, ast.Call)
        ]
        linears_by_class[cls.name.casefold()] = class_calls
    has_feed_forward = any(
        ("block" in name or "feedforward" in name or "mlp" in name)
        and class_calls.count("linear") >= 2
        and bool({"gelu", "relu", "silu"} & set(class_calls))
        for name, class_calls in linears_by_class.items()
    )
    if not has_norm or not has_feed_forward:
        checks.append("include a normalized residual feed-forward Transformer block")
    additions = sum(
        (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add))
        or (isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add))
        for node in ast.walk(tree)
    )
    if additions < 2:
        checks.append("use residual connections in the Transformer blocks")

    if not _has_shift(tree, left=True) or not _has_shift(tree, left=False):
        checks.append("train on paired next-token input and target slices")
    if not ("crossentropyloss" in call_names or "cross_entropy" in call_names):
        checks.append("compute next-token cross-entropy loss")
    if not _CHAR_VOCAB.search(code):
        checks.append(
            "derive character token IDs from the sample text instead of raw character codes"
        )
    return checks
