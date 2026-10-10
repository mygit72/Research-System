"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.chat import ChatMessage, Citation, Conversation, ConversationScope, MessageStatus
from app.models.comparison import Comparison, ComparisonStatus, PaperExtraction
from app.models.document import (
    Chunk,
    Document,
    DocumentElement,
    DocumentMetadata,
    DocumentReference,
    DocumentStatus,
    DocumentVersion,
    DuplicateKind,
    EmbeddingCache,
    IndexStatus,
    Page,
    Section,
)
from app.models.evaluation import EvalDataset, EvalItem, EvalRun
from app.models.job import Job, JobStatus
from app.models.knowledge import DocumentEntity, Entity, EntityExtraction, TopicClustering
from app.models.model_choice import UserModelChoice
from app.models.organization import (
    AnchorType,
    Bookmark,
    BookmarkKind,
    Collection,
    CollectionDocument,
    CollectionKind,
    DocumentTag,
    Note,
    ReadingStatus,
    Tag,
)
from app.models.project import ResearchProject
from app.models.report import ReportKind, ReportStatus, ResearchReport
from app.models.summary import PaperSummary, SummaryStatus
from app.models.usage import LLMUsage
from app.models.user import RefreshToken, User

__all__ = [
    "AnchorType",
    "AuditLog",
    "Base",
    "Bookmark",
    "BookmarkKind",
    "ChatMessage",
    "Chunk",
    "Citation",
    "Collection",
    "CollectionDocument",
    "CollectionKind",
    "Comparison",
    "ComparisonStatus",
    "Conversation",
    "ConversationScope",
    "Document",
    "DocumentElement",
    "DocumentEntity",
    "DocumentMetadata",
    "DocumentReference",
    "DocumentStatus",
    "DocumentTag",
    "DocumentVersion",
    "DuplicateKind",
    "EmbeddingCache",
    "Entity",
    "EntityExtraction",
    "EvalDataset",
    "EvalItem",
    "EvalRun",
    "IndexStatus",
    "Job",
    "JobStatus",
    "LLMUsage",
    "MessageStatus",
    "Note",
    "Page",
    "PaperExtraction",
    "PaperSummary",
    "ReadingStatus",
    "RefreshToken",
    "ReportKind",
    "ReportStatus",
    "ResearchProject",
    "ResearchReport",
    "Section",
    "SummaryStatus",
    "Tag",
    "TopicClustering",
    "User",
    "UserModelChoice",
]
