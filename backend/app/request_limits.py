"""Bound request bodies before FastAPI parses JSON or multipart form data."""
from starlette.responses import JSONResponse


class RequestBodyLimit:
    def __init__(self, app, *, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def too_large():
            response = JSONResponse({"detail": "Request body too large"}, status_code=413)
            await response(scope, receive, send)

        for key, value in scope["headers"]:
            if key == b"content-length" and value.isdigit() and int(value) > self.limit:
                await too_large()
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.limit:
                await too_large()
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        async def replay():
            nonlocal body
            if body is None:
                return await receive()
            message = {"type": "http.request", "body": bytes(body), "more_body": False}
            body = None
            return message

        await self.app(scope, replay, send)
