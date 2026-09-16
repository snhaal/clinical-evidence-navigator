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
) -> uuid.UUID:
    result = await conn.execute(
        text(
            """
            insert into patient_profiles (raw_text, structured_query, clarifying_question)
            values (:raw_text, :structured_query, :clarifying_question)
            returning id
            """
        ),
        {
            "raw_text": raw_text,
            "structured_query": json.dumps(structured_query)
            if structured_query is not None
            else None,
            "clarifying_question": clarifying_question,
        },
    )
    return result.scalar_one()
