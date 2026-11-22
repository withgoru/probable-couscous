"""Resend로 메일 한 통을 보내는 `Mailer` 구현(AC25, C12, C15, C17, T035).

다시 시도와 초당 상한, 수신 주소 비우기는 작업 스레드(`MailWorker`)가 맡는다. 여기서는 한 번 보내고 결과를 나눈다.
- 성공: 2xx
- 다시 시도: 429(서비스가 알려 준 대기 시간을 따른다), 5xx, 409 중 "나중에 다시"(처리 중·잠김), 연결 실패·시간 초과
- 포기: 그 밖의 4xx(키·권한·발신 도메인·입력 오류, 같은 키에 다른 내용)
API 키는 설정(환경 변수·.env)에서만 받고, 로그·오류 문구·출력 형태에 남기지 않는다. 서비스의 오류 문구에는 수신 주소가
섞일 수 있어 로그에는 상태 코드와 오류 이름만 남긴다(C11). 표준 라이브러리만 쓴다(C17).
"""

import json
import logging
import urllib.error
import urllib.request

from app.config import ConfigError, Settings
from app.mail import Mailer, MailError, MailMessage, OutboxMailer

log = logging.getLogger(__name__)

API_URL = "https://api.resend.com"
USER_AGENT = "classroom-server"
RETRY_LATER_409 = {"concurrent_idempotent_requests", "resource_locked"}


def _seconds(value: str | None) -> float | None:
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


class ResendMailer:
    def __init__(self, api_key: str, sender: str, base_url: str = API_URL, timeout: float = 10) -> None:
        if not api_key or not sender:
            raise ConfigError("RESEND_API_KEY와 MAIL_FROM을 모두 설정해 주세요.")
        self._api_key = api_key
        self._sender = sender
        self._url = base_url.rstrip("/") + "/emails"
        self._timeout = timeout

    def __repr__(self) -> str:  # 키를 보이지 않는다
        return f"ResendMailer(sender={self._sender!r}, url={self._url!r})"

    def send(self, message: MailMessage) -> None:
        body = json.dumps(
            {"from": self._sender, "to": [message.to], "subject": message.subject, "text": message.text}
        ).encode()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if message.idempotency_key:
            headers["Idempotency-Key"] = message.idempotency_key
        request = urllib.request.Request(self._url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                response.read()
                return
        except urllib.error.HTTPError as err:
            raise self._classify(err) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            reason = type(getattr(err, "reason", err)).__name__
            log.warning("Resend에 연결하지 못했습니다(%s). 다시 시도합니다.", reason)
            raise MailError(f"메일 서비스에 연결하지 못했습니다({reason}).", retryable=True) from None

    def _classify(self, err: urllib.error.HTTPError) -> MailError:
        status = err.code
        try:
            payload = json.loads(err.read() or b"{}")
        except ValueError:
            payload = {}
        name = payload.get("name") if isinstance(payload, dict) else None
        name = name if isinstance(name, str) else "unknown"
        if status == 429:
            wait = _seconds(err.headers.get("retry-after")) or _seconds(err.headers.get("ratelimit-reset"))
            log.warning("Resend가 요청을 잠시 막았습니다(429 %s). %s초 뒤 다시 시도합니다.", name, wait)
            return MailError(f"메일 서비스가 요청을 잠시 막았습니다(429 {name}).", retryable=True, retry_after=wait)
        if status >= 500 or status == 408 or (status == 409 and name in RETRY_LATER_409):
            log.warning("Resend가 일시적으로 실패했습니다(%s %s). 다시 시도합니다.", status, name)
            return MailError(f"메일 서비스가 일시적으로 실패했습니다({status} {name}).", retryable=True)
        log.error(
            "Resend가 메일을 거부했습니다(%s %s). 키, 발신 도메인 인증, MAIL_FROM을 확인해 주세요. 이 메일은 다시 보내지 않습니다.",
            status,
            name,
        )
        return MailError(f"메일 서비스가 메일을 거부했습니다({status} {name}).", retryable=False)


def mailer_from_settings(settings: Settings) -> Mailer:
    """키가 있으면 Resend로 보내고, 없으면 메모리에만 모은다(개발·테스트). 키만 있고 발신 주소가 없으면 설정 오류다."""
    if not settings.resend_api_key:
        return OutboxMailer()
    if not settings.mail_from:
        raise ConfigError(
            "RESEND_API_KEY는 있는데 MAIL_FROM이 비어 있습니다. Resend에서 인증한 도메인의 주소로 MAIL_FROM을 설정해 주세요."
        )
    return ResendMailer(settings.resend_api_key, settings.mail_from)
