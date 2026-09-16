from fastapi import APIRouter

from app.basecamp.critique_marker_detector import normalize_critique_marker
from app.models import MarkerDetectRequest, MarkerDetectResponse

router = APIRouter(prefix="/basecamp", tags=["basecamp"])


@router.post("/critique-marker/detect", response_model=MarkerDetectResponse)
def detect_marker(body: MarkerDetectRequest) -> MarkerDetectResponse:
    """Enforces REQ-001 over a single comment body. Does not yet create a
    Review Queue item (REQ-002) or touch MessageId/CommentId version
    identity — those depend on the Basecamp/SQL Server integration layer,
    which doesn't exist in this repo yet.
    """
    normalized = normalize_critique_marker(body.comment_body)
    return MarkerDetectResponse(is_critique_marker=normalized is not None, normalized_marker=normalized)
