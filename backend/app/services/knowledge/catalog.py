"""Built-in catalog of well-known datasets, models, methods, metrics and tasks.

The catalog is what makes extraction deterministic and inspectable: a mention is
linked to an entity because one of the entity's surface forms appears in the
paper, not because a model guessed. Names the catalog doesn't know are found by
the patterns in `extract.py` (acronym definitions, "we propose X", "the X dataset").

Matching rules (see `extract.CatalogMatcher`):
- acronyms and CamelCase ("BERT", "GLUE", "GloVe") and one-word model / dataset names
  ("Inception") are matched case-sensitively, everything else in any case
  ("Reciprocal rank fusion" also matches "reciprocal rank fusion");
- `variants=True` also matches size/version suffixes and links them to the family
  ("BERT-large", "BERTBASE", "GPT-3 175B", "ResNet-152" → BERT / GPT-3 / ResNet),
  keeping the variant as written.

`info` holds reference facts for well-known datasets (task, domain, size, license).
They are shown as "Built-in catalog" information, never as something a paper said,
and only facts that are stable and widely documented are included.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EntityType(StrEnum):
    DATASET = "dataset"
    MODEL = "model"
    METHOD = "method"
    METRIC = "metric"
    TASK = "task"


@dataclass(frozen=True)
class CatalogEntry:
    type: EntityType
    name: str
    aliases: tuple[str, ...] = ()
    variants: bool = False
    info: dict[str, str] = field(default_factory=dict)


def _d(name: str, *aliases: str, **info: str) -> CatalogEntry:
    return CatalogEntry(EntityType.DATASET, name, aliases, info=info)


def _m(name: str, *aliases: str, variants: bool = True) -> CatalogEntry:
    return CatalogEntry(EntityType.MODEL, name, aliases, variants=variants)


def _me(name: str, *aliases: str) -> CatalogEntry:
    return CatalogEntry(EntityType.METHOD, name, aliases)


def _mt(name: str, *aliases: str) -> CatalogEntry:
    return CatalogEntry(EntityType.METRIC, name, aliases)


def _t(name: str, *aliases: str) -> CatalogEntry:
    return CatalogEntry(EntityType.TASK, name, aliases)


DATASETS = [
    _d(
        "ImageNet",
        "ILSVRC",
        "ILSVRC-2012",
        "ILSVRC 2012",
        "ImageNet-1k",
        "ImageNet-1K",
        task="Image classification",
        domain="Natural images",
        size="ILSVRC-2012: about 1.28M training and 50k validation images, 1,000 classes",
    ),
    _d(
        "ImageNet-21k",
        "ImageNet-21K",
        "ImageNet-22k",
        task="Image classification (pre-training)",
        domain="Natural images",
        size="About 14M images, about 21k classes",
    ),
    _d(
        "JFT-300M",
        "JFT",
        task="Image classification (pre-training)",
        domain="Natural images",
        size="About 300M images; internal to Google, not publicly released",
    ),
    _d(
        "CIFAR-10",
        "CIFAR10",
        task="Image classification",
        domain="Natural images",
        size="60k 32×32 images, 10 classes",
    ),
    _d(
        "CIFAR-100",
        "CIFAR100",
        task="Image classification",
        domain="Natural images",
        size="60k 32×32 images, 100 classes",
    ),
    _d(
        "MNIST",
        task="Image classification",
        domain="Handwritten digits",
        size="70k 28×28 grayscale images, 10 classes",
    ),
    _d(
        "COCO",
        "MS COCO",
        "MS-COCO",
        "MSCOCO",
        task="Object detection, segmentation, captioning",
        domain="Natural images",
        size="About 330k images, 80 object categories",
        license="Annotations CC BY 4.0",
    ),
    _d(
        "PASCAL VOC",
        "VOC 2007",
        "VOC 2012",
        "VOC2007",
        "VOC2012",
        task="Object detection, segmentation",
        domain="Natural images",
        size="20 object classes",
    ),
    _d(
        "Oxford-IIIT Pets",
        "Oxford-IIIT Pet",
        task="Fine-grained image classification",
        domain="Pet photos",
        size="About 7.4k images, 37 breeds",
    ),
    _d(
        "Oxford Flowers-102",
        "Oxford Flowers",
        "Flowers-102",
        "Flowers102",
        task="Fine-grained image classification",
        domain="Flower photos",
        size="102 classes",
    ),
    _d(
        "VTAB",
        "VTAB-1k",
        task="Transfer learning benchmark",
        domain="Images",
        size="19 tasks, 1,000 training examples each",
    ),
    _d(
        "GLUE",
        task="Natural language understanding benchmark",
        domain="English text",
        size="9 sentence and sentence-pair tasks",
    ),
    _d(
        "SuperGLUE",
        task="Natural language understanding benchmark",
        domain="English text",
        size="8 tasks",
    ),
    _d(
        "MNLI",
        "MultiNLI",
        "Multi-Genre NLI",
        task="Natural language inference",
        domain="English text, several genres",
        size="About 433k sentence pairs",
    ),
    _d(
        "SNLI",
        task="Natural language inference",
        domain="Image captions",
        size="About 570k sentence pairs",
    ),
    _d(
        "SST-2",
        "SST",
        "Stanford Sentiment Treebank",
        task="Sentiment classification",
        domain="Movie reviews",
    ),
    _d("CoLA", task="Linguistic acceptability", domain="English sentences"),
    _d("QNLI", task="Natural language inference (from SQuAD)", domain="Wikipedia"),
    _d("QQP", "Quora Question Pairs", task="Paraphrase detection", domain="Quora questions"),
    _d("RTE", task="Textual entailment", domain="News, Wikipedia"),
    _d("MRPC", task="Paraphrase detection", domain="News"),
    _d("STS-B", "STS Benchmark", task="Semantic textual similarity", domain="Mixed English"),
    _d("WNLI", task="Coreference / inference", domain="English sentences"),
    _d(
        "SWAG",
        task="Commonsense inference",
        domain="Video captions",
        size="About 113k multiple-choice questions",
    ),
    _d(
        "SQuAD",
        "SQuAD v1.1",
        "SQuAD 1.1",
        "SQuAD v2.0",
        "SQuAD 2.0",
        "SQuADv2",
        task="Extractive question answering",
        domain="Wikipedia",
        size="v1.1: 100k+ questions; v2.0 adds about 50k unanswerable questions",
        license="CC BY-SA 4.0",
    ),
    _d(
        "Natural Questions",
        "NaturalQuestions",
        task="Open-domain question answering",
        domain="Google search queries, Wikipedia",
        size="About 307k training examples",
        license="CC BY-SA 3.0",
    ),
    _d(
        "TriviaQA",
        task="Question answering",
        domain="Trivia questions, Wikipedia and web",
        size="About 650k question-answer-evidence triples",
    ),
    _d("WebQuestions", "WebQ", task="Question answering", domain="Google Suggest, Freebase"),
    _d(
        "CuratedTREC",
        "CuratedTrec",
        "TREC QA",
        task="Question answering",
        domain="TREC QA questions",
    ),
    _d(
        "HotpotQA",
        task="Multi-hop question answering",
        domain="Wikipedia",
        size="About 113k questions",
        license="CC BY-SA 4.0",
    ),
    _d(
        "MS MARCO",
        "MSMARCO",
        "MS-MARCO",
        task="Passage ranking, question answering",
        domain="Bing search queries, web passages",
        size="Passage ranking: about 8.8M passages and 1M queries",
    ),
    _d("TREC CAR", "TREC-CAR", task="Passage retrieval", domain="Wikipedia"),
    _d("BEIR", task="Zero-shot retrieval benchmark", domain="Mixed", size="18 datasets"),
    _d("FEVER", task="Fact verification", domain="Wikipedia", size="About 185k claims"),
    _d("KILT", task="Knowledge-intensive tasks benchmark", domain="Wikipedia"),
    _d("Jeopardy", task="Question generation", domain="Jeopardy! questions"),
    _d(
        "MMLU",
        task="Multitask knowledge evaluation",
        domain="57 subjects",
        size="About 16k multiple-choice questions",
        license="MIT",
    ),
    _d(
        "GSM8K",
        task="Math word problems",
        domain="Grade-school math",
        size="About 8.5k problems",
        license="MIT",
    ),
    _d("HumanEval", task="Code generation", domain="Python", size="164 problems", license="MIT"),
    _d("HellaSwag", task="Commonsense inference", domain="Video captions, WikiHow"),
    _d(
        "WikiText-103",
        "WikiText103",
        "WikiText-2",
        "WikiText",
        task="Language modeling",
        domain="Wikipedia",
        size="WikiText-103: about 103M tokens",
    ),
    _d("Penn Treebank", "PTB", task="Language modeling, parsing", domain="Wall Street Journal"),
    _d(
        "WMT 2014 English-German",
        "WMT14 En-De",
        "WMT 2014 En-De",
        "WMT'14 En-De",
        "WMT 2014 English-to-German",
        task="Machine translation",
        domain="News",
        size="About 4.5M sentence pairs",
    ),
    _d(
        "WMT 2014 English-French",
        "WMT14 En-Fr",
        "WMT 2014 En-Fr",
        "WMT 2014 English-to-French",
        task="Machine translation",
        domain="News",
        size="About 36M sentence pairs",
    ),
    _d("WMT", task="Machine translation", domain="News"),
    _d(
        "CNN/DailyMail",
        "CNN/Daily Mail",
        "CNN-DM",
        task="Summarization",
        domain="News",
        size="About 300k articles",
    ),
    _d("XSum", task="Summarization", domain="BBC news", size="About 227k articles"),
    _d("E2E NLG", "E2E", task="Data-to-text generation", domain="Restaurant descriptions"),
    _d("WebNLG", task="Data-to-text generation", domain="DBpedia triples"),
    _d("DART", task="Data-to-text generation", domain="Open-domain tables"),
    _d("WikiSQL", task="Text-to-SQL", domain="Wikipedia tables"),
    _d("SAMSum", task="Dialogue summarization", domain="Messenger-style dialogues"),
    _d("BookCorpus", "BooksCorpus", task="Pre-training corpus", domain="Books"),
    _d("English Wikipedia", task="Pre-training corpus", domain="Encyclopedia"),
    _d("C4", task="Pre-training corpus", domain="Web text (Common Crawl)"),
    _d("Common Crawl", "CommonCrawl", task="Pre-training corpus", domain="Web text"),
    _d("OpenWebText", task="Pre-training corpus", domain="Web text"),
    _d("CC-News", "CC-NEWS", task="Pre-training corpus", domain="News"),
    _d("The Pile", task="Pre-training corpus", domain="Mixed text"),
    _d("OASST1", "OpenAssistant", task="Instruction tuning", domain="Assistant conversations"),
    _d("Alpaca", task="Instruction tuning", domain="Generated instructions"),
    _d("FLAN v2", "FLAN", task="Instruction tuning", domain="Mixed tasks"),
    _d("Self-Instruct", task="Instruction tuning", domain="Generated instructions"),
    _d("Vicuna benchmark", task="Chatbot evaluation", domain="Questions"),
]

MODELS = [
    _m("Transformer", "Transformers", variants=False),
    _m("BERT", "BERTBASE", "BERTLARGE", "BERT-Base", "BERT-Large"),
    _m("RoBERTa"),
    _m("ALBERT"),
    _m("DistilBERT"),
    _m("DeBERTa", "DeBERTaV3"),
    _m("ELECTRA"),
    _m("XLNet"),
    _m("SpanBERT"),
    _m("ColBERT", "ColBERTv2"),
    _m("DPR", "Dense Passage Retriever", "Dense Passage Retrieval"),
    _m("Contriever"),
    _m("ANCE"),
    _m("SPLADE"),
    _m("Sentence-BERT", "SBERT"),
    _m("GPT", variants=False),
    _m("GPT-2", "GPT2"),
    _m("GPT-3", "GPT3"),
    _m("GPT-3.5", "ChatGPT"),
    _m("GPT-4", "GPT4"),
    _m("T5", "Flan-T5", "FLAN-T5"),
    _m("BART"),
    _m("ELMo", variants=False),
    _m("LLaMA", "LLaMa", "Llama", "LLaMA-2", "Llama 2", "Llama-2"),
    _m("Guanaco"),
    _m("Vicuna"),
    _m("Mistral"),
    _m("OPT"),
    _m("BLOOM"),
    _m("PaLM"),
    _m("Megatron", "Megatron-LM"),
    _m("ResNet", "ResNets"),
    _m("ResNeXt"),
    _m("VGG", "VGGNet", "VGG-16", "VGG-19"),
    _m("AlexNet", variants=False),
    _m("GoogLeNet", "Inception", variants=False),
    _m("EfficientNet"),
    _m("ViT", "Vision Transformer", "Vision Transformers"),
    _m("BiT", "Big Transfer"),
    _m("DeiT"),
    _m("Swin Transformer", "Swin"),
    _m("CLIP"),
    _m("U-Net", "UNet", variants=False),
    _m("Faster R-CNN", variants=False),
    _m("Mask R-CNN", variants=False),
    _m("YOLO"),
    _m("LSTM", "LSTMs", "long short-term memory", variants=False),
    _m("GRU", variants=False),
    _m("seq2seq", "sequence-to-sequence", variants=False),
    _m("ConvS2S", variants=False),
    _m("ByteNet", variants=False),
    _m("Word2Vec", "word2vec", variants=False),
    _m("GloVe", variants=False),
]

METHODS = [
    _me("LoRA", "Low-Rank Adaptation", "low-rank adaptation"),
    _me("QLoRA"),
    _me("Adapters", "adapter tuning", "adapter modules", "adapter layers", "Adapter"),
    _me("Prefix-tuning", "prefix-tuning", "prefix tuning", "Prefix tuning"),
    _me("Prompt tuning", "prompt tuning"),
    _me("P-tuning"),
    _me("BitFit"),
    _me(
        "Parameter-efficient fine-tuning",
        "parameter-efficient fine-tuning",
        "PEFT",
        "parameter-efficient transfer learning",
    ),
    _me("Knowledge distillation", "knowledge distillation", "distillation"),
    _me("Quantization", "quantization", "4-bit quantization", "8-bit quantization"),
    _me("NormalFloat (NF4)", "NF4", "NormalFloat", "4-bit NormalFloat"),
    _me("Double quantization", "double quantization", "Double Quantization"),
    _me("Paged optimizers", "paged optimizers", "Paged Optimizers"),
    _me("Gradient checkpointing", "gradient checkpointing"),
    _me("Mixed-precision training", "mixed precision", "mixed-precision", "fp16 training"),
    _me(
        "Instruction tuning",
        "instruction tuning",
        "instruction finetuning",
        "instruction fine-tuning",
    ),
    _me("RLHF", "reinforcement learning from human feedback"),
    _me(
        "Masked language modeling",
        "masked language model",
        "masked language modeling",
        "MLM",
        "Masked LM",
        "masked LM",
    ),
    _me("Next sentence prediction", "next sentence prediction", "NSP"),
    _me("Self-attention", "self-attention", "Self-Attention"),
    _me("Multi-head attention", "multi-head attention", "Multi-Head Attention"),
    _me(
        "Scaled dot-product attention",
        "scaled dot-product attention",
        "Scaled Dot-Product Attention",
    ),
    _me(
        "Positional encoding",
        "positional encoding",
        "positional encodings",
        "position embeddings",
        "positional embeddings",
    ),
    _me(
        "Residual connections",
        "residual connection",
        "residual connections",
        "residual learning",
        "shortcut connections",
        "skip connections",
    ),
    _me("Batch normalization", "batch normalization", "BatchNorm", "batch norm"),
    _me("Layer normalization", "layer normalization", "LayerNorm", "layer norm"),
    _me("Dropout", "dropout"),
    _me("Label smoothing", "label smoothing"),
    _me("Data augmentation", "data augmentation"),
    _me("Contrastive learning", "contrastive learning", "contrastive loss"),
    _me("In-batch negatives", "in-batch negatives", "in-batch negative"),
    _me("Hard negative mining", "hard negatives", "hard negative mining"),
    _me("Late interaction", "late interaction"),
    _me("Cross-encoder", "cross-encoder", "cross-encoders"),
    _me("Bi-encoder", "bi-encoder", "dual encoder", "dual-encoder", "two-tower"),
    _me("Maximum inner product search", "maximum inner product search", "MIPS"),
    _me(
        "Approximate nearest neighbor search",
        "approximate nearest neighbor",
        "nearest neighbor search",
        "ANN search",
    ),
    _me("FAISS", "Faiss"),
    _me("BM25", "Okapi BM25"),
    _me("TF-IDF", "tf-idf", "TF–IDF"),
    _me("Reciprocal rank fusion", "reciprocal rank fusion", "RRF"),
    _me("Reranking", "reranking", "re-ranking", "reranker", "re-ranker"),
    _me(
        "Retrieval-augmented generation",
        "retrieval-augmented generation",
        "Retrieval-Augmented Generation",
        "retrieval augmented generation",
        "RAG",
    ),
    _me("Beam search", "beam search"),
    _me("Greedy decoding", "greedy decoding"),
    _me("Adam", "AdamW", "Adam optimizer"),
    _me("Stochastic gradient descent", "stochastic gradient descent", "SGD"),
    _me("Learning rate warmup", "warmup", "learning rate warm-up", "linear warmup"),
    _me("Byte-pair encoding", "byte-pair encoding", "byte pair encoding", "BPE"),
    _me("WordPiece", "wordpiece"),
    _me("SentencePiece"),
    _me("Pre-training", "pre-training", "pretraining", "pre-trained", "pretrained"),
    _me("Fine-tuning", "fine-tuning", "finetuning", "fine-tuned", "finetuned"),
    _me("Transfer learning", "transfer learning"),
    _me("Few-shot learning", "few-shot", "few shot"),
    _me("Zero-shot learning", "zero-shot", "zero shot"),
    _me("In-context learning", "in-context learning"),
    _me("Chain-of-thought prompting", "chain-of-thought", "chain of thought"),
    _me(
        "Convolutional neural network",
        "convolutional neural network",
        "convolutional neural networks",
        "CNN",
        "CNNs",
        "ConvNet",
        "ConvNets",
    ),
    _me(
        "Recurrent neural network",
        "recurrent neural network",
        "recurrent neural networks",
        "RNN",
        "RNNs",
    ),
    _me("Mixture of experts", "mixture of experts", "mixture-of-experts", "MoE"),
    _me("Singular value decomposition", "singular value decomposition", "SVD"),
]

METRICS = [
    _mt("Accuracy", "accuracy"),
    _mt("Top-1 accuracy", "top-1 accuracy", "Top-1 accuracy", "top-1 error"),
    _mt("Top-5 accuracy", "top-5 accuracy", "Top-5 accuracy", "top-5 error"),
    _mt("Error rate", "error rate", "error rates"),
    _mt("F1", "F1 score", "F1-score", "F1 scores", "macro-F1", "micro-F1"),
    _mt("Exact match", "exact match", "Exact Match", "EM score"),
    _mt("Precision", "precision"),
    _mt("Recall", "recall"),
    _mt("Recall@k", "Recall@k", "recall@k", "Recall@K", "R@k"),
    _mt("Precision@k", "Precision@k", "precision@k", "P@k"),
    _mt("MRR", "mean reciprocal rank", "MRR@10", "Mean Reciprocal Rank"),
    _mt("nDCG", "NDCG", "nDCG@10", "NDCG@10", "normalized discounted cumulative gain"),
    _mt("MAP", "mean average precision", "Mean Average Precision"),
    _mt(
        "Top-k retrieval accuracy",
        "top-20 accuracy",
        "top-100 accuracy",
        "top-k accuracy",
        "Top-20 accuracy",
        "Top-100 accuracy",
    ),
    _mt("BLEU", "BLEU score", "SacreBLEU"),
    _mt("ROUGE", "ROUGE-L", "ROUGE-1", "ROUGE-2", "Rouge-L", "ROUGE score"),
    _mt("METEOR"),
    _mt("CIDEr"),
    _mt("NIST"),
    _mt("TER"),
    _mt("BERTScore"),
    _mt("Perplexity", "perplexity", "PPL"),
    _mt("Matthews correlation", "Matthews correlation", "Matthew's correlation", "MCC"),
    _mt("Pearson correlation", "Pearson correlation", "Spearman correlation"),
    _mt("AUC", "ROC AUC", "AUROC"),
    _mt("mAP (detection)", "box AP", "AP50", "AP75"),
    _mt("Latency", "latency"),
    _mt("Throughput", "throughput"),
    _mt("FLOPs", "FLOPS", "GFLOPs"),
    _mt("Elo rating", "Elo"),
]

TASKS = [
    _t("Question answering", "question answering", "Question Answering", "QA"),
    _t(
        "Open-domain question answering",
        "open-domain question answering",
        "Open-Domain Question Answering",
        "open-domain QA",
        "ODQA",
    ),
    _t(
        "Extractive question answering",
        "extractive question answering",
        "reading comprehension",
        "machine reading comprehension",
    ),
    _t(
        "Passage retrieval",
        "passage retrieval",
        "passage ranking",
        "passage search",
        "Passage Search",
        "document retrieval",
        "dense retrieval",
        "Dense Retrieval",
    ),
    _t(
        "Information retrieval",
        "information retrieval",
        "Information Retrieval",
        "ad-hoc retrieval",
    ),
    _t("Machine translation", "machine translation", "Machine Translation", "translation task"),
    _t("Summarization", "summarization", "abstractive summarization", "text summarization"),
    _t("Language modeling", "language modeling", "language modelling", "Language Modeling"),
    _t("Natural language inference", "natural language inference", "textual entailment", "NLI"),
    _t(
        "Natural language understanding", "natural language understanding", "Language Understanding"
    ),
    _t("Sentiment analysis", "sentiment analysis", "sentiment classification"),
    _t("Named entity recognition", "named entity recognition", "NER"),
    _t("Text classification", "text classification"),
    _t("Text generation", "text generation", "natural language generation", "NLG"),
    _t("Table-to-text generation", "table-to-text", "data-to-text"),
    _t("Fact verification", "fact verification", "fact checking", "fact-checking"),
    _t("Question generation", "question generation"),
    _t("Dialogue", "dialogue systems", "dialogue generation", "chatbot"),
    _t("Instruction following", "instruction following", "instruction-following"),
    _t(
        "Image classification",
        "image classification",
        "Image Classification",
        "image recognition",
        "Image Recognition",
    ),
    _t("Object detection", "object detection", "Object Detection"),
    _t("Semantic segmentation", "semantic segmentation", "image segmentation"),
    _t("Image captioning", "image captioning"),
    _t("Constituency parsing", "constituency parsing", "English Constituency Parsing"),
    _t("Code generation", "code generation"),
    _t("Mathematical reasoning", "math reasoning", "mathematical reasoning"),
]

CATALOG: list[CatalogEntry] = [*DATASETS, *MODELS, *METHODS, *METRICS, *TASKS]
