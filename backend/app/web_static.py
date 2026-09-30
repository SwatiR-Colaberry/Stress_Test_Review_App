"""Static files for the reviewer pages (/queue/, /reviewer/, /rules/).

Every file is served with "Cache-Control: no-cache": the browser may keep a
copy but must check with the server (a cheap ETag round trip, 304 if
unchanged) before using it. Without it, browsers reuse cached copies on
their own schedule, and a page could run a new script against an old shared
file (seen 2026-09-30: new queue page + old reviewer.css / review_logic.js ->
unstyled header and an empty queue).
"""
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class RevalidatedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response
