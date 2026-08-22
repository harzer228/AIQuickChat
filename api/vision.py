"""Cloudflare Workers AI vision client.

Uses the official Workers AI REST API:
    POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}
with body: {"image": "<base64>", "prompt": "..."}
"""

import base64
import io
import mimetypes
from pathlib import Path

import httpx
from PIL import Image

from api.errors import APIError
from utils.i18n import t

VISION_SYSTEM_PROMPT = (
    "You are a precise image analysis assistant. Analyze the provided image "
    "carefully and extract all information that may be useful for another AI "
    "model answering the user's question.\n\n"

    "Follow these rules:\n"
    "1. Describe only information that is actually visible in the image.\n"
    "2. Do not invent, assume, or hallucinate missing information.\n"
    "3. Clearly distinguish visible facts from uncertain or partially visible details.\n"
    "4. Read and reproduce visible text as accurately as possible.\n"
    "5. Pay special attention to screenshots, software interfaces, error messages, "
    "code, buttons, menus, dialogs, notifications, and other UI elements.\n"
    "6. Describe the location and relationship of important elements "
    "(top/bottom, left/right, center, inside/outside, etc.).\n"
    "7. If an error, warning, exception, or technical problem is visible, "
    "identify it and transcribe the relevant message exactly when possible.\n"
    "8. For code or logs, preserve the visible text, symbols, numbers, and formatting "
    "as accurately as possible.\n"
    "9. Ignore irrelevant visual details unless they help answer the user's question.\n"
    "10. If something cannot be read or identified confidently, explicitly say so "
    "instead of guessing.\n\n"

    "Analyze the image using this structure when applicable:\n"
    "- IMAGE TYPE: What kind of image this is (screenshot, photo, diagram, UI, etc.).\n"
    "- MAIN CONTENT: What is primarily shown.\n"
    "- TEXT: All important visible text, including labels, messages, titles, and numbers.\n"
    "- UI ELEMENTS: Buttons, tabs, menus, panels, icons, fields, dialogs, indicators, etc.\n"
    "- OBJECTS: Important visible objects and their characteristics.\n"
    "- POSITIONS: Important spatial relationships and locations.\n"
    "- TECHNICAL DETAILS: Software names, versions, errors, logs, code, settings, "
    "hardware information, or other technical information.\n"
    "- PROBLEMS/WARNINGS: Visible errors, warnings, crashes, unusual behavior, "
    "or suspicious details.\n"
    "- IMPORTANT DETAILS: Any other information that may help another AI answer "
    "the user's question.\n\n"

    "Output a concise but sufficiently detailed factual description. "
    "Prioritize accuracy, readable text, technical information, and details "
    "relevant to understanding the image. "
    "Do not provide solutions or speculate unless the user explicitly asks for them."
)


def build_vision_prompt(user_question: str = "") -> str:
    """Build the prompt sent to the vision model (image + optional question)."""
    prompt = VISION_SYSTEM_PROMPT
    if user_question:
        prompt += f'\n\nUser question:\n"{user_question}"'
    return prompt


def build_deepseek_image_message(description: str, user_question: str = "") -> str:
    """Build the DeepSeek user message from a vision description."""
    return (
        "Пользователь отправил изображение.\n\n"
        "Описание изображения, полученное от Vision AI:\n\n"
        f"{description}\n\n"
        "Вопрос пользователя:\n\n"
        f"{user_question or '(без вопроса)'}\n\n"
        "Ответь пользователю на основе изображения и его вопроса. "
        "Не упоминай, что изображение обрабатывалось отдельной vision-моделью. "
        "Если описания недостаточно для ответа — честно скажи, "
        "что на изображении невозможно определить нужную информацию."
    )


class CloudflareVisionClient:
    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, account_id: str = "", api_token: str = "", model: str = "",
                 timeout: float = 120.0):
        self.account_id = (account_id or "").strip()
        self.api_token = (api_token or "").strip()
        self.model = (model or "").strip()
        self.timeout = timeout

    def _require_config(self):
        if not self.account_id:
            raise APIError(t("vision.no_account"), code="no_account")
        if not self.api_token:
            raise APIError(t("vision.no_token"), code="no_token")
        if not self.model:
            raise APIError(t("vision.no_model"), code="no_model")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        return f"{self.BASE}/accounts/{self.account_id}/ai/run/{self.model}"

    def _post(self, payload: dict, timeout: float | None = None) -> "httpx.Response":
        try:
            return httpx.post(
                self._url(), json=payload, headers=self._headers(),
                timeout=timeout or self.timeout)
        except httpx.TimeoutException:
            raise APIError(t("vision.timeout"), code="timeout")
        except httpx.ConnectError:
            raise APIError(t("vision.network"), code="network")
        except httpx.HTTPError as e:
            raise APIError(t("vision.network_err", e=e), code="network", detail=str(e))

    @staticmethod
    def _is_agreement_error(resp: "httpx.Response") -> bool:
        """True if Cloudflare requires accepting the model license ('agree')."""
        body = (resp.text or "").lower()
        return ("model agreement" in body
                or "must submit the prompt 'agree'" in body
                or "community license" in body
                or "agree" in body and "license" in body)

    def _send_agree(self, timeout: float | None = None) -> bool:
        """Accept the model license by sending the prompt 'agree'."""
        try:
            resp = httpx.post(
                self._url(), json={"prompt": "agree"}, headers=self._headers(),
                timeout=timeout or self.timeout)
            return resp.status_code == 200 and resp.json().get("success", False)
        except Exception:
            return False

    @staticmethod
    def _translate_http_error(status: int, body: str) -> APIError:
        snippet = (body or "")[:600]
        if status == 401:
            return APIError(t("vision.auth"), code="auth", detail=snippet)
        if status == 403:
            return APIError(t("vision.forbidden"), code="forbidden", detail=snippet)
        if status == 404:
            return APIError(t("vision.not_found"), code="not_found", detail=snippet)
        if status == 429:
            return APIError(t("vision.rate_limit"), code="rate_limit", detail=snippet)
        if status >= 500:
            return APIError(t("vision.server", status=status), code="server", detail=snippet)
        if status >= 400:
            return APIError(t("vision.client_error", status=status), code="client_error", detail=snippet)
        return APIError(t("vision.http", status=status), code="http", detail=snippet)

    def _parse_payload_result(self, payload: dict, timeout: float | None = None) -> dict:
        """Send a request, auto-accepting the license on first use, return JSON body."""
        resp = self._post(payload, timeout)
        if self._is_agreement_error(resp):
            # First-time license acceptance for llama-3.2 vision models.
            self._send_agree(timeout)
            resp = self._post(payload, timeout)
        if resp.status_code != 200:
            raise self._translate_http_error(resp.status_code, resp.text or "")
        try:
            data = resp.json()
        except ValueError:
            raise APIError(
                t("vision.json"),
                code="json", detail=(resp.text or "")[:600])
        if not data.get("success"):
            errors = data.get("errors") or []
            detail = "; ".join(
                f"{e.get('code')}: {e.get('message')}" if isinstance(e, dict) else str(e)
                for e in errors
            ) or str(data)[:600]
            # Retry once if the agreement came back inside a 200 body.
            if "model agreement" in detail.lower() or "agree" in detail.lower():
                self._send_agree(timeout)
                resp = self._post(payload, timeout)
                if resp.status_code != 200:
                    raise self._translate_http_error(resp.status_code, resp.text or "")
                try:
                    data = resp.json()
                except ValueError:
                    raise APIError(
                        t("vision.json"),
                        code="json", detail=(resp.text or "")[:600])
                if not data.get("success"):
                    errors = data.get("errors") or []
                    detail = "; ".join(
                        f"{e.get('code')}: {e.get('message')}" if isinstance(e, dict) else str(e)
                        for e in errors
                    ) or str(data)[:600]
                    raise APIError(t("vision.cloudflare_error"), code="cloudflare", detail=detail)
            else:
                raise APIError(t("vision.cloudflare_error"), code="cloudflare", detail=detail)
        return data

    def analyze_image_bytes(self, image_bytes: bytes, prompt: str,
                            mime: str = "image/png",
                            timeout: float | None = None) -> str:
        self._require_config()
        mime = mime or "image/png"
        data_uri = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "image": data_uri,
            "prompt": prompt,
        }
        data = self._parse_payload_result(payload, timeout)

        result = data.get("result") or {}
        if isinstance(result, str):
            description = result.strip()
        else:
            description = (result.get("response")
                           or result.get("description")
                           or result.get("content") or "").strip()
        if not description:
            raise APIError(
                t("vision.empty"), code="empty",
                detail=str(result)[:600])
        return description

    def analyze_image_file(self, path, prompt: str, timeout: float | None = None) -> str:
        p = Path(path)
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        return self.analyze_image_bytes(p.read_bytes(), prompt, mime=mime, timeout=timeout)

    def test_connection(self, timeout: float = 60.0) -> str:
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (180, 40, 40)).save(buf, "PNG")
        desc = self.analyze_image_bytes(
            buf.getvalue(),
            "Describe this image in one short sentence.",
            timeout=timeout)
        if not desc.strip():
            raise APIError(t("vision.empty_test"), code="empty")
        return desc.strip()
