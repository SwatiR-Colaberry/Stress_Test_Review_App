from fastapi import APIRouter

from app.guardrails.credential_leak_guardrail import scan_text_for_credentials
from app.models import CredentialFinding, ScanTextRequest, ScanTextResponse

router = APIRouter(prefix="/security", tags=["security"])


@router.post("/scan-credentials", response_model=ScanTextResponse)
def scan_credentials(body: ScanTextRequest) -> ScanTextResponse:
    """Enforces REQ-016 over arbitrary text (e.g. a document about to be
    shared) rather than a repo file — see backend/scripts/scan_for_credentials.py
    for the repo-wide walker used in CI/local enforcement.
    """
    findings = scan_text_for_credentials(body.content)
    return ScanTextResponse(
        safe=len(findings) == 0,
        findings=[CredentialFinding(**f) for f in findings],
    )
