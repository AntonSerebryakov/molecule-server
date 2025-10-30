# models.py
from datetime import datetime
from sqlalchemy import String, DateTime, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from database import Base  # или from smiles_search.database import Base


class MoleculeORM(Base):
    __tablename__ = "molecules"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    smiles: Mapped[str] = mapped_column(String, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("smiles", name="uq_molecules_smiles"),
    )
