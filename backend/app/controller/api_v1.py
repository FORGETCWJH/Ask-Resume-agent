from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..dto.base import ApiModel
from ..dto.conversation import ConversationCreate, ConversationGroupCreate, ConversationGroupOut, ConversationOut, ConversationPatch, MessageCreate, MessageOut, QuestionBatchOut, SupplementOut, SupplementUpdate
from ..dto.agent_follow_up import LlmRunCreateOut, LlmRunOut, PracticeAnswerCreate, PracticeAnswerOut, PracticeTurnListOut, QuestionScope
from ..dto.material import EvidenceOut, MaterialSetCreate, MaterialSetOut, MaterialSummary, RecognitionConfirm, RecognitionOut, RecognitionPatch, RecognitionRetry
from ..service.conversation_service import ConversationService
from ..service.material_service import MaterialService
from ..service.resume_recognition_service import ResumeRecognitionService
from ..service.agent_follow_up_service import AgentFollowUpService
from ..service.practice_service import PracticeService
from ..dto.practice import PracticeInputCreate, NavigationCreate, PreferencePatch
from ..models import LlmRun


router = APIRouter(prefix="/api/v1")


@router.get("/conversations/{conversation_id}/resume-snapshots")
def resume_snapshots(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    return PracticeService(db).snapshots(conversation_id)


@router.post("/conversations/{conversation_id}/input-runs", status_code=202)
def practice_input(conversation_id: str, payload: PracticeInputCreate, db: Session = Depends(get_db)) -> dict:
    return PracticeService(db).submit(conversation_id, payload.content, payload.client_request_id)


@router.get("/conversations/{conversation_id}/practice-state")
def practice_state(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    return PracticeService(db).state(conversation_id)


@router.get("/conversations/{conversation_id}/practice-messages")
def practice_messages(conversation_id: str, after_sequence: int = Query(0, ge=0, alias="afterSequence"), limit: int = Query(100, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    return PracticeService(db).messages(conversation_id, after_sequence, limit)


@router.post("/conversations/{conversation_id}/navigation-events", status_code=201)
def practice_navigation(conversation_id: str, payload: NavigationCreate, db: Session = Depends(get_db)) -> dict:
    return PracticeService(db).next_question(conversation_id, payload.client_request_id)


@router.get("/practice-preferences")
def practice_preferences(db: Session = Depends(get_db)) -> list:
    return PracticeService(db).preferences()


@router.patch("/practice-preferences/{preference_id}")
def patch_practice_preference(preference_id: str, payload: PreferencePatch, db: Session = Depends(get_db)) -> dict:
    return PracticeService(db).patch_preference(preference_id, payload.value, payload.expected_revision)


@router.delete("/practice-preferences/{preference_id}", status_code=204)
def delete_practice_preference(preference_id: str, db: Session = Depends(get_db)) -> Response:
    PracticeService(db).delete_preference(preference_id)
    return Response(status_code=204)


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


@router.get("/material-sets/{set_id}/conversations", response_model=list[ConversationOut])
def list_conversations(set_id: str, status: str = Query("all"), q: str | None = Query(None), group_id: str | None = Query(None, alias="groupId"), db: Session = Depends(get_db)) -> list[ConversationOut]:
    return ConversationService(db).list_for_set(set_id, status, q, group_id)


@router.get("/material-sets/{set_id}/conversation-groups", response_model=list[ConversationGroupOut])
def list_conversation_groups(set_id: str, db: Session = Depends(get_db)) -> list[ConversationGroupOut]:
    return ConversationService(db).groups(set_id)


@router.post("/material-sets/{set_id}/conversation-groups", response_model=ConversationGroupOut, status_code=status.HTTP_201_CREATED)
def create_conversation_group(set_id: str, payload: ConversationGroupCreate, db: Session = Depends(get_db)) -> ConversationGroupOut:
    return ConversationService(db).create_group(set_id, payload.name)


@router.patch("/conversation-groups/{group_id}", response_model=ConversationGroupOut)
def update_conversation_group(group_id: str, payload: ConversationGroupCreate, db: Session = Depends(get_db)) -> ConversationGroupOut:
    return ConversationService(db).update_group(group_id, payload.name)


@router.delete("/conversation-groups/{group_id}", status_code=204)
def delete_conversation_group(group_id: str, db: Session = Depends(get_db)) -> Response:
    ConversationService(db).delete_group(group_id)
    return Response(status_code=204)


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


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def update_conversation(conversation_id: str, payload: ConversationPatch, db: Session = Depends(get_db)) -> ConversationOut:
    return ConversationService(db).update_management(conversation_id, payload)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)) -> Response:
    ConversationService(db).delete_conversation(conversation_id)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageEnvelope, status_code=status.HTTP_201_CREATED)
async def send_message(conversation_id: str, payload: MessageCreate, db: Session = Depends(get_db)) -> MessageEnvelope:
    message = await ConversationService(db).send(conversation_id, payload.content, payload.mode, payload.selection.text if payload.selection else None)
    return MessageEnvelope(message=message)


@router.patch("/conversations/{conversation_id}/supplements/{supplement_id}", response_model=SupplementOut)
def confirm_supplement(conversation_id: str, supplement_id: str, payload: SupplementUpdate, db: Session = Depends(get_db)) -> SupplementOut:
    return ConversationService(db).confirm_supplement(conversation_id, supplement_id, payload.content)


@router.post("/conversations/{conversation_id}/question-runs", response_model=LlmRunCreateOut, status_code=status.HTTP_202_ACCEPTED)
def create_question_run(conversation_id: str, payload: QuestionScope, db: Session = Depends(get_db)) -> LlmRunCreateOut:
    run = AgentFollowUpService(db).create_question_run(conversation_id, payload)
    return LlmRunCreateOut(run_id=run.id, status=run.status, run_type=run.kind, conversation_id=run.conversation_id, practice_turn_id=run.practice_turn_id)


@router.get("/conversations/{conversation_id}/practice-turns", response_model=PracticeTurnListOut)
def list_practice_turns(conversation_id: str, db: Session = Depends(get_db)) -> PracticeTurnListOut:
    return AgentFollowUpService(db).list_turns(conversation_id)


@router.post("/practice-turns/{turn_id}/answers", response_model=PracticeAnswerOut, status_code=status.HTTP_201_CREATED)
def save_practice_answer(turn_id: str, payload: PracticeAnswerCreate, db: Session = Depends(get_db)) -> PracticeAnswerOut:
    return AgentFollowUpService(db).save_answer(turn_id, payload.content)


@router.post("/practice-turns/{turn_id}/reference-answer-runs", response_model=LlmRunCreateOut, status_code=status.HTTP_202_ACCEPTED)
def create_reference_answer_run(turn_id: str, db: Session = Depends(get_db)) -> LlmRunCreateOut:
    run = AgentFollowUpService(db).create_reference_run(turn_id)
    return LlmRunCreateOut(run_id=run.id, status=run.status, run_type=run.kind, conversation_id=run.conversation_id, practice_turn_id=run.practice_turn_id)


@router.post("/practice-turns/{turn_id}/feedback-runs", response_model=LlmRunCreateOut, status_code=status.HTTP_202_ACCEPTED)
def create_feedback_run(turn_id: str, db: Session = Depends(get_db)) -> LlmRunCreateOut:
    run = AgentFollowUpService(db).create_feedback_run(turn_id)
    return LlmRunCreateOut(run_id=run.id, status=run.status, run_type=run.kind, conversation_id=run.conversation_id, practice_turn_id=run.practice_turn_id)


@router.post("/practice-turns/{turn_id}/follow-up-runs", response_model=LlmRunCreateOut, status_code=status.HTTP_202_ACCEPTED)
def create_follow_up_run(turn_id: str, db: Session = Depends(get_db)) -> LlmRunCreateOut:
    run = AgentFollowUpService(db).create_follow_up_run(turn_id)
    return LlmRunCreateOut(run_id=run.id, status=run.status, run_type=run.kind, conversation_id=run.conversation_id, practice_turn_id=run.practice_turn_id)


@router.get("/llm-runs/{run_id}", response_model=LlmRunOut)
def get_llm_run(run_id: str, db: Session = Depends(get_db)) -> LlmRunOut:
    return AgentFollowUpService(db).get_run(run_id)


@router.post("/llm-runs/{run_id}/retry", response_model=LlmRunCreateOut, status_code=status.HTTP_202_ACCEPTED)
def retry_llm_run(run_id: str, db: Session = Depends(get_db)) -> LlmRunCreateOut:
    service = AgentFollowUpService(db)
    run = service.retry_run(run_id)
    return LlmRunCreateOut(run_id=run.id, status=run.status, run_type=run.kind, conversation_id=run.conversation_id, practice_turn_id=run.practice_turn_id)


@router.post("/llm-runs/{run_id}/cancel", response_model=LlmRunOut)
def cancel_llm_run(run_id: str, db: Session = Depends(get_db)) -> LlmRunOut:
    return AgentFollowUpService(db).cancel_run(run_id)
