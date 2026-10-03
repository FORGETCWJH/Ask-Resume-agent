from .dto.conversation import ConversationCreate, MessageCreate, SupplementUpdate
from .dto.llm import StructuredResponse
from .dto.material import MaterialSetCreate

SupplementConfirm = SupplementUpdate

__all__ = ["ConversationCreate", "MessageCreate", "MaterialSetCreate", "SupplementConfirm", "StructuredResponse"]
