"""Bounded request metadata only: never record transcript text or raw URLs."""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger('echo.requests')


class RequestHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            print(self.format(record), file=sys.stdout, flush=True)
        except Exception:
            self.handleError(record)


class RequestFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'event': 'http_request',
            'request_id': record.request_id,
            'method': record.http_method,
            'route': record.route_template,
            'status': record.http_status,
            'duration_ms': record.duration_ms,
            'outcome': record.outcome,
        }, ensure_ascii=True)


class RedactServerException(logging.Filter):
    """Uvicorn re-logs raised ASGI errors after the application handles them."""
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info or record.exc_text:
            record.msg = 'Unhandled server error; inspect echo.requests for the request reference.'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def configure_request_logging() -> None:
    if not any(getattr(handler, '_echo_request_handler', False) for handler in logger.handlers):
        handler = RequestHandler()
        handler.setFormatter(RequestFormatter())
        handler._echo_request_handler = True
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Default access records contain raw paths and search query strings.
    logging.getLogger('uvicorn.access').disabled = True
    server_logger = logging.getLogger('uvicorn.error')
    if not any(isinstance(item, RedactServerException) for item in server_logger.filters):
        server_logger.addFilter(RedactServerException())


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        started = perf_counter()
        status = 500
        outcome = 'completed'
        response_started = False

        async def send_with_reference(message: Message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                status = message['status']
                response_started = True
                message = {**message, 'headers': [
                    (key, value) for key, value in message.get('headers', [])
                    if key.lower() != b'x-request-id'
                ] + [(b'x-request-id', request_id.encode('ascii'))]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_reference)
        except asyncio.CancelledError:
            outcome = 'cancelled'
            if not response_started:
                status = 499
            raise
        except Exception:
            outcome = 'error'
            raise
        finally:
            route = scope.get('route')
            method = scope.get('method', '')
            logger.info('http_request', extra={
                'request_id': request_id,
                'http_method': method if method in {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT'} else 'OTHER',
                'route_template': getattr(route, 'path', '<unmatched>'),
                'http_status': status,
                'duration_ms': round((perf_counter() - started) * 1000, 2),
                'outcome': outcome,
            })
