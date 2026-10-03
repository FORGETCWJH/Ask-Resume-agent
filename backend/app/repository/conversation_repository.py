import json

from sqlalchemy.orm import Session

from ..models import Conversation, Message


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, conversation_id: str) -> Conversation | None:
        return self.db.get(Conversation, conversation_id)

    def messages(self, conversation_id: str) -> list[Message]:
        return self.db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at.asc()).all()

    @staticmethod
    def response(message: Message) -> dict | None:
        return json.loads(message.response_json) if message.response_json else None

