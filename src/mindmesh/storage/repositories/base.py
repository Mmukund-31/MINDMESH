from __future__ import annotations

from ..db import Database


class ScopedRepo:
    """Base for repositories. Every query is filtered by ``project_id``; there is no unscoped path."""

    def __init__(self, db: Database, project_id: str):
        if not project_id:
            raise ValueError("project_id is required")
        self.db = db
        self.project_id = project_id
