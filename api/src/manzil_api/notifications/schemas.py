from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

NotificationEventType = Literal[
    "checkpoint_waiting",
    "run_failed",
    "listing_score_changed",
    "comment_added",
    "rating_changed",
]
EVENTS = {
    "checkpoint_waiting",
    "run_failed",
    "listing_score_changed",
    "comment_added",
    "rating_changed",
}


class AccountNotificationPreferences(BaseModel):
    email: dict[NotificationEventType, bool]

    @model_validator(mode="after")
    def exact_events(self) -> AccountNotificationPreferences:
        if set(self.email) != EVENTS:
            raise ValueError("email preferences must contain every notification event exactly once")
        return self


class HuntNotificationPreferences(BaseModel):
    account_email: dict[NotificationEventType, bool]
    email_overrides: dict[NotificationEventType, bool | None]
    effective_email: dict[NotificationEventType, bool]

    @model_validator(mode="after")
    def exact_events(self) -> HuntNotificationPreferences:
        for value in (self.account_email, self.email_overrides, self.effective_email):
            if set(value) != EVENTS:
                raise ValueError(
                    "Hunt preferences must contain every notification event exactly once"
                )
        return self


class HuntNotificationPreferenceUpdate(BaseModel):
    email_overrides: dict[NotificationEventType, bool | None]

    @model_validator(mode="after")
    def exact_events(self) -> HuntNotificationPreferenceUpdate:
        if set(self.email_overrides) != EVENTS:
            raise ValueError(
                "Hunt preference overrides must contain every notification event exactly once"
            )
        return self


class AttentionResponse(BaseModel):
    waiting_checkpoint_count: int
    failed: int = 0
    waiting_user: int = 0
    running: int = 0
    task_status: Literal["failed", "waiting_user", "running"] | None = None
