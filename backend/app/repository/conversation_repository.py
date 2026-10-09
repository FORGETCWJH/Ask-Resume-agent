import json

from sqlalchemy.orm import Session

from ..models import Conversation, ConversationGroup, Message


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, conversation_id: str) -> Conversation | None:
        return self.db.get(Conversation, conversation_id)

    def messages(self, conversation_id: str) -> list[Message]:
        return self.db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at.asc()).all()

    def group(self, group_id: str) -> ConversationGroup | None:
        return self.db.get(ConversationGroup, group_id)

    def groups_for_set(self, set_id: str) -> list[ConversationGroup]:
        return self.db.query(ConversationGroup).filter(ConversationGroup.material_set_id == set_id).order_by(ConversationGroup.created_at.asc(), ConversationGroup.id.asc()).all()

    @staticmethod
    def response(message: Message) -> dict | None:
        return json.loads(message.response_json) if message.response_json else None

