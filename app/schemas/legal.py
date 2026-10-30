"""Esquemas de consentimientos legales."""

from datetime import datetime

from pydantic import BaseModel


class ConsentAccepted(BaseModel):
    accepted: bool
    document: str
    version: str
    accepted_at: datetime
