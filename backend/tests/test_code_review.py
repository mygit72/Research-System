from app.services.rag.code_review import review_generated_code

VALID_GPT = '''```python
import math
import torch
from torch import nn
import torch.nn.functional as F

text = "tiny sample text"
chars = sorted(set(text))
stoi = {char: index for index, char in enumerate(chars)}

class CausalSelfAttention(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.queries = nn.Linear(width, width)
        self.keys = nn.Linear(width, width)
        self.values = nn.Linear(width, width)

    def forward(self, x, mask):
        q = self.queries(x)
        k = self.keys(x)
        v = self.values(x)
        scores = q @ k.transpose(-2, -1) / math.sqrt(x.size(-1))
        scores = scores.masked_fill(mask == 0, float("-inf"))
        weights = F.softmax(scores, dim=-1)
        return weights @ v

class TransformerBlock(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.attention = CausalSelfAttention(width)
        self.norm = nn.LayerNorm(width)
        self.mlp = nn.Sequential(nn.Linear(width, 16), nn.GELU(), nn.Linear(16, width))

    def forward(self, x, mask):
        x = x + self.attention(self.norm(x), mask)
        return x + self.mlp(self.norm(x))

class GPT(nn.Module):
    def __init__(self, vocab_size, block_size, width):
        super().__init__()
        self.token_embedding = nn.Embedding(vocab_size, width)
        self.position_embedding = nn.Embedding(block_size, width)
        self.blocks = nn.ModuleList([TransformerBlock(width)])
        self.lm_head = nn.Linear(width, vocab_size)

    def forward(self, tokens):
        positions = torch.arange(tokens.size(1))
        x = self.token_embedding(tokens) + self.position_embedding(positions)
        mask = torch.tril(torch.ones(tokens.size(1), tokens.size(1)))
        for block in self.blocks:
            x = block(x, mask)
        return self.lm_head(x)

tokens = torch.tensor([[stoi[char] for char in text]])
x = tokens[:, :-1]
y = tokens[:, 1:]
model = GPT(len(chars), block_size=64, width=16)
logits = model(x)
loss = nn.CrossEntropyLoss()(logits.reshape(-1, len(chars)), y.reshape(-1))
```'''


def test_gpt_code_review_accepts_a_minimal_decoder_only_structure() -> None:
    assert review_generated_code(VALID_GPT, gpt=True) == []


def test_gpt_code_review_catches_unused_projections_and_missing_attention_math() -> None:
    unused_query = VALID_GPT.replace("q = self.queries(x)", "q = x")
    assert "use the query, key, and value projections in the attention calculation" in (
        review_generated_code(unused_query, gpt=True)
    )

    missing_value_mix = VALID_GPT.replace("return weights @ v", "return v")
    assert "compute attention scores, normalize them, and combine them with values" in (
        review_generated_code(missing_value_mix, gpt=True)
    )


def test_gpt_code_review_accepts_common_training_text_and_vocabulary_names() -> None:
    answer = VALID_GPT.replace("text", "training_data").replace("stoi", "char_to_index")
    assert review_generated_code(answer, gpt=True) == []


def test_gpt_code_review_rejects_a_generic_transformer_draft() -> None:
    answer = '''```python
import torch
from torch import nn

class SelfAttention(nn.Module):
    def forward(self, x):
        return x

class GPT(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(27, 8)

text = "hello world"
tokens = torch.tensor([[ord(char) for char in text]])
```'''
    issues = review_generated_code(answer, gpt=True)
    assert "add a learned position embedding and use it with the token embedding" in issues
    assert "build and apply a causal attention mask" in issues
    assert "train on paired next-token input and target slices" in issues
    assert "derive character token IDs from the sample text instead of raw character codes" in issues


def test_code_review_catches_python_syntax_errors_and_missing_code() -> None:
    assert review_generated_code("```python\ndef broken(:\n```") == [
        "Python code block 1 has a syntax error on line 1"
    ]
    assert review_generated_code("Here is the approach.") == [
        "include the complete implementation in a code block"
    ]
