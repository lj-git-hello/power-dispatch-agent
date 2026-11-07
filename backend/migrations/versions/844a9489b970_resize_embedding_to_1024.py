"""resize_embedding_to_1024

Revision ID: 844a9489b970
Revises: f36cb2d88733
Create Date: 2026-11-07 16:20:45.249716

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '844a9489b970'
down_revision: Union[str, Sequence[str], None] = 'f36cb2d88733'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """1536 -> 1024。

    知识库已物理清空（旧伪向量脏数据），无需数据保维度，直接改列类型。
    HNSW 依赖列类型，须先删除、改型后按 1024 重建。
    """
    op.execute("DROP INDEX IF EXISTS idx_knowledge_embedding_hnsw;")
    op.execute(
        "ALTER TABLE ai_knowledge_base "
        "ALTER COLUMN embedding TYPE vector(1024);"
    )
    op.execute(
        "CREATE INDEX idx_knowledge_embedding_hnsw ON ai_knowledge_base "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64);"
    )


def downgrade() -> None:
    """1024 -> 1536。"""
    op.execute("DROP INDEX IF EXISTS idx_knowledge_embedding_hnsw;")
    op.execute(
        "ALTER TABLE ai_knowledge_base "
        "ALTER COLUMN embedding TYPE vector(1536);"
    )
    op.execute(
        "CREATE INDEX idx_knowledge_embedding_hnsw ON ai_knowledge_base "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64);"
    )
