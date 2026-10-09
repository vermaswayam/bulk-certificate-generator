from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.schemas import RecipientIn


@dataclass
class InvalidRow:
    index: int
    errors: list[str]
    name: str | None = None
    email: str | None = None


def format_errors(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"])
        messages.append(f"{field}: {err['msg']}" if field else err["msg"])
    return messages


def _raw_field(item: Any, key: str) -> str | None:
    if isinstance(item, dict) and item.get(key) is not None:
        return str(item[key])[:255]
    return None


def validate_recipients(raw: list[Any]) -> tuple[list[tuple[int, RecipientIn]], list[InvalidRow]]:
    """Validate each recipient on its own.

    Returns (valid, invalid). Valid entries keep their original index so the
    client can match results back to the list they sent.
    """
    valid: list[tuple[int, RecipientIn]] = []
    invalid: list[InvalidRow] = []
    seen_emails: set[str] = set()

    for index, item in enumerate(raw):
        try:
            recipient = RecipientIn.model_validate(item)
        except ValidationError as exc:
            invalid.append(InvalidRow(index, format_errors(exc), _raw_field(item, "name"), _raw_field(item, "email")))
            continue

        email_key = recipient.email.lower()
        if email_key in seen_emails:
            invalid.append(
                InvalidRow(index, ["email: duplicate recipient in this request"], recipient.name, recipient.email)
            )
            continue

        seen_emails.add(email_key)
        valid.append((index, recipient))

    return valid, invalid
