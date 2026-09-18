"""
Repository for patient_profiles. Plain SQL via SQLAlchemy Core (text()) —
no ORM — so every query is visible and reviewable, per the project's
architecture principle.
"""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def insert_patient_profile(
    conn: AsyncConnection,
    raw_text: str,
    structured_query: dict | None,
    clarifying_question: str | None,
    user_id: str | None = None,
) -> uuid.UUID:
    parsed_user_id = uuid.UUID(user_id) if user_id else None
    result = await conn.execute(
        text(
            """
            insert into patient_profiles (raw_text, structured_query, clarifying_question, user_id)
            values (:raw_text, :structured_query, :clarifying_question, :user_id)
            returning id
            """
        ),
        {
            "raw_text": raw_text,
            "structured_query": json.dumps(structured_query)
            if structured_query is not None
            else None,
            "clarifying_question": clarifying_question,
            "user_id": parsed_user_id,
        },
    )
    return result.scalar_one()


async def delete_patient_profile(
    conn: AsyncConnection,
    profile_id: str | uuid.UUID,
    user_id: str | uuid.UUID,
) -> str:
    """
    Deletes a patient_profile and cascades to match_runs and criterion_verdicts.
    Enforces tenancy ownership:
    Returns:
      'not_found' if profile does not exist
      'forbidden' if profile belongs to another user
      'deleted' if successfully deleted
    """
    parsed_profile_id = (
        uuid.UUID(str(profile_id))
        if not isinstance(profile_id, uuid.UUID)
        else profile_id
    )
    parsed_user_id = (
        uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
    )

    check_res = await conn.execute(
        text("select user_id from patient_profiles where id = :profile_id"),
        {"profile_id": parsed_profile_id},
    )
    row = check_res.mappings().first()
    if not row:
        return "not_found"

    if row["user_id"] is None or str(row["user_id"]) != str(parsed_user_id):
        return "forbidden"

    await conn.execute(
        text("delete from patient_profiles where id = :profile_id and user_id = :user_id"),
        {"profile_id": parsed_profile_id, "user_id": parsed_user_id},
    )
    return "deleted"

