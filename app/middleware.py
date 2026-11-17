import json
import threading
import time
from collections import defaultdict, deque

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'"
)
DOCS_PATHS = ("/docs", "/redoc")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"origin-agent-cluster", b"?1"),
    (b"x-dns-prefetch-control", b"off"),
    (b"x-download-options", b"noopen"),
    (b"x-permitted-cross-domain-policies", b"none"),
    (b"x-xss-protection", b"0"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


async def send_json(send: Send, status: int, body: dict, headers: list[tuple[bytes, bytes]] = ()) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            *headers,
        ],
    })
    await send({"type": "http.response.body", "body": payload})


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_docs = scope["path"].startswith(DOCS_PATHS)
        csp = (DOCS_CSP if is_docs else API_CSP).encode()

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"server"]
                present = {k.lower() for k, _ in headers}
                for key, value in [*SECURITY_HEADERS, (b"content-security-policy", csp)]:
                    if key not in present:
                        headers.append((key, value))
                if not is_docs and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope.get("headers", [])).get(b"content-length")
        if length is not None:
            try:
                too_large = int(length) > self.max_bytes
            except ValueError:
                return await send_json(send, 400, {"detail": "En-tête Content-Length invalide"})
            if too_large:
                return await send_json(send, 413, {"detail": "Requête trop volumineuse"})

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(413, "Requête trop volumineuse")
            return message

        await self.app(scope, limited_receive, send)


class RateLimiter:
    def __init__(self, global_limit: int, login_limit: int, login_window_seconds: int, enabled: bool = True):
        self.enabled = enabled
        self.global_limit = global_limit
        self.global_window = 3600
        self.login_limit = login_limit
        self.login_window = login_window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _purge(self, key: str, window: int, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        return hits

    def retry_after(self, key: str, limit: int, window: int) -> int | None:
        with self._lock:
            now = time.monotonic()
            hits = self._purge(key, window, now)
            if len(hits) >= limit:
                return int(hits[0] + window - now) + 1
            return None

    def hit(self, key: str, window: int) -> None:
        with self._lock:
            now = time.monotonic()
            self._purge(key, window, now).append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RateLimitMiddleware:
    LOGIN_PATH = "/auth/login"

    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limiter = self.limiter
        if scope["type"] != "http" or not limiter.enabled or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)

        client = (scope.get("client") or ("unknown", 0))[0]
        is_login = scope["path"] == self.LOGIN_PATH and scope["method"] == "POST"

        if is_login:
            wait = limiter.retry_after(f"login:{client}", limiter.login_limit, limiter.login_window)
            if wait is not None:
                return await self._reject(send, wait, limiter.login_limit,
                                          "Trop de tentatives de connexion, réessayez dans 15 minutes")

        global_key = f"global:{client}"
        wait = limiter.retry_after(global_key, limiter.global_limit, limiter.global_window)
        if wait is not None:
            return await self._reject(send, wait, limiter.global_limit,
                                      "Trop de requêtes, réessayez plus tard")
        limiter.hit(global_key, limiter.global_window)

        if not is_login:
            return await self.app(scope, receive, send)

        async def watch_login(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 401:
                limiter.hit(f"login:{client}", limiter.login_window)
            await send(message)

        await self.app(scope, receive, watch_login)

    @staticmethod
    async def _reject(send: Send, wait: int, limit: int, detail: str) -> None:
        await send_json(send, 429, {"detail": detail}, [
            (b"retry-after", str(wait).encode()),
            (b"ratelimit-limit", str(limit).encode()),
            (b"ratelimit-remaining", b"0"),
            (b"ratelimit-reset", str(wait).encode()),
        ])
