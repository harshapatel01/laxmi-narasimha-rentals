import json
from urllib.error import URLError
from urllib.request import Request, urlopen


def send_brevo_email(
    *,
    api_key: str,
    sender_email: str,
    sender_name: str,
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str,
) -> None:
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": text_content,
        "htmlContent": html_content,
    }
    request = Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise URLError(f"Brevo returned HTTP {response.status}.")
