from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..dto.base import ApiModel
from ..dto.conversation import ConversationCreate, ConversationOut, MessageCreate, MessageOut, QuestionBatchOut, SupplementOut, SupplementUpdate
from ..dto.material import EvidenceOut, MaterialSetCreate, MaterialSetOut, MaterialSummary, RecognitionConfirm, RecognitionOut, RecognitionPatch, RecognitionRetry
from ..service.conversation_service import ConversationService
from ..service.material_service import MaterialService
from ..service.resume_recognition_service import ResumeRecognitionService


router = APIRouter(prefix="/api/v1")


class MessageEnvelope(ApiModel):
    message: MessageOut


@router.get("/health")
def health() -> dict:
    from ..config import settings

    return {"status": "ok", "llmConfigured": bool(settings.llm_api_key)}


@router.post("/material-sets", response_model=MaterialSetOut, status_code=status.HTTP_201_CREATED)
def create_material_set(payload: MaterialSetCreate, db: Session = Depends(get_db)) -> MaterialSetOut:
    return MaterialService(db).create(payload.title)


@router.get("/material-sets", response_model=list[MaterialSetOut])
def list_material_sets(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)) -> list[MaterialSetOut]:
    return MaterialService(db).list_sets(limit, offset)


@router.get("/material-sets/{set_id}", response_model=MaterialSetOut)
def get_material_set(set_id: str, db: Session = Depends(get_db)) -> MaterialSetOut:
    service = MaterialService(db)
    return service.serialize(service.get(set_id))


@router.delete("/material-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material_set(set_id: str, db: Session = Depends(get_db)) -> Response:
    MaterialService(db).delete(set_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/material-sets/{set_id}/materials", response_model=MaterialSetOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_material(set_id: str, kind: str = Query(..., pattern="^(resume|projectArchive)$"), file: UploadFile = File(...), db: Session = Depends(get_db)) -> MaterialSetOut:
    normalized = "project_archive" if kind == "projectArchive" else kind
    return await MaterialService(db).upload(set_id, file, normalized)


@router.get("/material-sets/{set_id}/materials", response_model=list[MaterialSummary])
def list_materials(set_id: str, db: Session = Depends(get_db)) -> list[MaterialSummary]:
    service = MaterialService(db)
    item = service.get(set_id)
    return service.serialize(item).materials


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(material_id: str, db: Session = Depends(get_db)) -> Response:
    MaterialService(db).delete_material(material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/materials/{material_id}/retry", response_model=MaterialSetOut)
def retry_project_material(material_id: str, db: Session = Depends(get_db)) -> MaterialSetOut:
    return MaterialService(db).retry_project(material_id)


@router.get("/material-sets/{set_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(set_id: str, query: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[EvidenceOut]:
    return MaterialService(db).evidence(set_id, query)


@router.get("/materials/{material_id}/recognition", response_model=RecognitionOut)
async def get_resume_recognition(material_id: str, db: Session = Depends(get_db)) -> RecognitionOut:
    return ResumeRecognitionService(db).get(material_id)


@router.patch("/materials/{material_id}/recognition", response_model=RecognitionOut)
def update_resume_recognition(material_id: str, payload: RecognitionPatch, db: Session = Depends(get_db)) -> RecognitionOut:
    return ResumeRecognitionService(db).update(material_id, payload.draft)


@router.post("/materials/{material_id}/recognition/retry", response_model=RecognitionOut)
async def retry_resume_recognition(material_id: str, payload: RecognitionRetry, db: Session = Depends(get_db)) -> RecognitionOut:
    return await ResumeRecognitionService(db).retry(material_id, payload.scope, payload.page_number)


@router.post("/materials/{material_id}/recognition/confirm", response_model=RecognitionOut)
def confirm_resume_recognition(material_id: str, payload: RecognitionConfirm, db: Session = Depends(get_db)) -> RecognitionOut:
    return ResumeRecognitionService(db).confirm(material_id, payload.section)


@router.post("/material-sets/{set_id}/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(set_id: str, payload: ConversationCreate, db: Session = Depends(get_db)) -> ConversationOut:
    return ConversationService(db).create(set_id, payload.title)


@router.post("/material-sets/{set_id}/question-batches", response_model=QuestionBatchOut, status_code=status.HTTP_201_CREATED)
async def generate_question_batch(set_id: str, db: Session = Depends(get_db)) -> QuestionBatchOut:
    service = ConversationService(db)
    conversation = service.create(set_id, "自动问题批次")
    message = await service.send(conversation.id, "请基于当前材料生成 8 个由浅入深的问题，覆盖事实、实现细节、技术取舍、指标、失败和扩展设计。每个问题都必须引用证据。", "generateQuestions", None)
    response = message.response or {}
    return QuestionBatchOut(id=message.id, conversation_id=conversation.id, status="ready", questions=response.get("questions", []), evidence=response.get("evidence", []))


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)) -> ConversationOut:
    service = ConversationService(db)
    return service.serialize(service.get(conversation_id))


@router.post("/conversations/{conversation_id}/messages", response_model=MessageEnvelope, status_code=status.HTTP_201_CREATED)
async def send_message(conversation_id: str, payload: MessageCreate, db: Session = Depends(get_db)) -> MessageEnvelope:
    message = await ConversationService(db).send(conversation_id, payload.content, payload.mode, payload.selection.text if payload.selection else None)
    return MessageEnvelope(message=message)


@router.patch("/conversations/{conversation_id}/supplements/{supplement_id}", response_model=SupplementOut)
def confirm_supplement(conversation_id: str, supplement_id: str, payload: SupplementUpdate, db: Session = Depends(get_db)) -> SupplementOut:
    return ConversationService(db).confirm_supplement(conversation_id, supplement_id, payload.content)
