"""Managing reviewers and admins (STORY-014, REQ-020). Admins only.

GET    /admin-ui/roles         everyone on the lists (bootstrap admins first)
PUT    /admin-ui/roles/{email} add someone or change their role; body {"role": "reviewer" | "admin"}
DELETE /admin-ui/roles/{email} remove someone

Every change, and every refused change, is audited by RoleStore with who,
whose role and when. Repeating a change is safe: it answers "unchanged" /
"not_found" and records nothing new.

Status codes: 401 not signed in; 403 not an admin (ADMIN_ONLY); 409 refused
(BOOTSTRAP_ADMIN, LAST_ADMIN); 422 not an email address; 503 the role list
or the audit trail is unavailable (nothing changed; retrying is safe).
"""
import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel

from app.audit.trail import AuditWriteError
from app.auth.config import MAX_EMAIL_LENGTH, InvalidEmail, normalize_email
from app.auth.dependencies import get_role_store
from app.auth.guards import require_admin
from app.auth.roles import Role, RoleAssignment, RoleChangeRefused, RoleStore, RoleStoreUnavailable
from app.auth.sessions import Principal

router = APIRouter(prefix="/admin-ui", tags=["admin"])

EmailPath = Path(max_length=MAX_EMAIL_LENGTH)
CorrelationHeader = Header(default=None, max_length=64)


class RoleRequest(BaseModel):
    role: Role


class RoleChange(BaseModel):
    email: str
    role: Optional[Role] = None
    result: Literal["added", "changed", "unchanged", "removed", "not_found"]


@router.get("/roles", response_model=List[RoleAssignment])
def list_roles(admin: Principal = Depends(require_admin),
               roles: RoleStore = Depends(get_role_store)) -> List[RoleAssignment]:
    return _run(roles.list_assignments)


@router.put("/roles/{email}", response_model=RoleChange)
def set_role(body: RoleRequest, email: str = EmailPath, admin: Principal = Depends(require_admin),
             roles: RoleStore = Depends(get_role_store),
             x_correlation_id: Optional[str] = CorrelationHeader) -> RoleChange:
    target = _email(email)
    result = _run(lambda: roles.set_role(target, body.role, admin.email, x_correlation_id or str(uuid.uuid4())))
    return RoleChange(email=target, role=body.role, result=result)


@router.delete("/roles/{email}", response_model=RoleChange)
def remove_role(email: str = EmailPath, admin: Principal = Depends(require_admin),
                roles: RoleStore = Depends(get_role_store),
                x_correlation_id: Optional[str] = CorrelationHeader) -> RoleChange:
    target = _email(email)
    result = _run(lambda: roles.remove(target, admin.email, x_correlation_id or str(uuid.uuid4())))
    return RoleChange(email=target, result=result)


def _email(raw: str) -> str:
    try:
        return normalize_email(raw)
    except InvalidEmail as exc:
        raise HTTPException(422, {"reason_code": "INVALID_EMAIL", "message": str(exc)}) from exc


def _run(call):
    try:
        return call()
    except RoleChangeRefused as exc:
        raise HTTPException(409, {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except (RoleStoreUnavailable, AuditWriteError) as exc:
        raise HTTPException(503, {"error_class": exc.error_class,
                                  "message": "Nothing changed: the role list or the audit trail is unavailable. "
                                             "Retry; it is safe."}) from exc
