"""DeepSeek / RouterAI OpenAI-compatible chat client."""

import json
from collections.abc import Generator
from threading import Event

import httpx

from api.errors import APIError, GenerationCancelled
from utils.i18n import t


class DeepSeekClient:
    def __init__(self, api_url: str = "", api_key: str = "", model: str = "",
                 timeout: float = 120.0, stream_timeout: float | None = None):
        self.api_url = (api_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout = timeout
        self.stream_timeout = stream_timeout or (timeout * 2)
        self._active_response = None

    # -- config checks ------------------------------------------------------

    def _require_config(self):
        if not self.api_key:
            raise APIError(t("api.no_key"), code="no_api_key")
        if not self.api_url:
            raise APIError(t("api.no_url"), code="no_url")
        if not self.model:
            raise APIError(t("api.no_model"), code="no_model")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self) -> str:
        return f"{self.api_url}/chat/completions"

    # -- error translation --------------------------------------------------

    @staticmethod
    def _translate_http_error(status: int, body: str) -> APIError:
        snippet = (body or "")[:600]
        if status == 400:
            return APIError(t("api.http_400"), code="bad_request", detail=snippet)
        if status == 401:
            return APIError(t("api.http_401"), code="auth", detail=snippet)
        if status == 403:
            return APIError(t("api.http_403"), code="forbidden", detail=snippet)
        if status == 404:
            return APIError(t("api.http_404"), code="not_found", detail=snippet)
        if status == 429:
            return APIError(t("api.http_429"), code="rate_limit", detail=snippet)
        if 400 <= status < 500:
            return APIError(t("api.http_client", status=status), code="client_error", detail=snippet)
        if status >= 500:
            return APIError(t("api.http_server", status=status), code="server", detail=snippet)
        return APIError(t("api.http_other", status=status), code="http", detail=snippet)

    # -- public API ---------------------------------------------------------

    def send_message(self, messages: list[dict], timeout: float | None = None) -> str:
        """Send a non-streaming request, return the assistant text."""
        self._require_config()
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0.7,
        }
        try:
            resp = httpx.post(
                self._chat_url(), json=payload, headers=self._headers(),
                timeout=timeout or self.timeout)
        except httpx.TimeoutException:
            raise APIError(t("api.timeout"), code="timeout")
        except httpx.ConnectError:
            raise APIError(t("api.network"), code="network")
        except httpx.HTTPError as e:
            raise APIError(t("api.network_err", e=e), code="network", detail=str(e))

        if resp.status_code != 200:
            raise self._translate_http_error(resp.status_code, resp.text or "")

        try:
            data = resp.json()
        except ValueError:
            raise APIError(
                t("api.json"), code="json",
                detail=(resp.text or "")[:600])

        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise APIError(t("api.empty"), code="empty", detail=str(data)[:600])
        return content

    def stream_message(self, messages: list[dict],
                       cancel_event: Event | None = None) -> Generator[str, None, None]:
        """Stream an assistant answer chunk by chunk (yields text pieces).

        If `cancel_event` is provided and becomes set (or `cancel()` is called),
        the request is aborted and `GenerationCancelled` is raised.
        """
        self._require_config()
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
        }
        try:
            with httpx.stream(
                    "POST", self._chat_url(), json=payload, headers=self._headers(),
                    timeout=self.stream_timeout) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", "replace")
                    raise self._translate_http_error(resp.status_code, body)
                self._active_response = resp
                got_any = False
                for line in resp.iter_lines():
                    if cancel_event is not None and cancel_event.is_set():
                        raise GenerationCancelled()
                    line = (line or "").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    try:
                        delta = obj["choices"][0]["delta"].get("content") or ""
                    except (KeyError, IndexError, TypeError):
                        continue
                    if delta:
                        got_any = True
                        yield delta
                if not got_any and not (cancel_event is not None and cancel_event.is_set()):
                    raise APIError(t("api.empty"), code="empty")
        except GenerationCancelled:
            raise
        except httpx.TimeoutException:
            raise APIError(t("api.timeout"), code="timeout")
        except httpx.ConnectError:
            raise APIError(t("api.network"), code="network")
        except httpx.HTTPError as e:
            if cancel_event is not None and cancel_event.is_set():
                raise GenerationCancelled()
            raise APIError(t("api.network_err", e=e), code="network", detail=str(e))
        finally:
            self._active_response = None

    def cancel(self):
        """Abort the in-flight streaming request (thread-safe)."""
        resp = self._active_response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def test_connection(self, timeout: float = 30.0) -> str:
        reply = self.send_message(
            [{"role": "user", "content": "Reply with the single word: OK"}],
            timeout=timeout)
        if not reply.strip():
            raise APIError("API вернул пустой ответ.", code="empty")
        return reply.strip()
