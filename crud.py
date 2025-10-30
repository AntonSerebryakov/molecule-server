from typing import AsyncIterator, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from models import MoleculeORM
from schemas import Molecule, MoleculeUpdate


async def create_molecule(session: AsyncSession, data: Molecule) -> Molecule:
    exists = await session.get(MoleculeORM, data.id)
    if exists:
        raise ValueError("Molecule ID already exists")
    obj = MoleculeORM(id=data.id, smiles=data.smiles)
    session.add(obj)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise ValueError("Molecule with this SMILES already exists") from e
    return data


async def iter_molecules(
    session: AsyncSession,
    *,
    limit: Optional[int] = None,
    offset: int = 0,
    chunk_size: int = 500,
) -> AsyncIterator[Molecule]:
    stmt = select(MoleculeORM).order_by(MoleculeORM.id)

    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    stmt = stmt.execution_options(
        stream_results=True,
        yield_per=min(chunk_size, (limit or chunk_size)),
    )

    stream = await session.stream_scalars(stmt)
    try:
        async for m in stream:
            yield Molecule(id=m.id, smiles=m.smiles)
    finally:
        await stream.close()


async def update_molecule(session: AsyncSession, molecule_id: str,
                          data: MoleculeUpdate) -> Molecule:
    obj = await session.get(MoleculeORM, molecule_id)
    if not obj:
        return None
    await session.execute(
        update(MoleculeORM)
        .where(MoleculeORM.id == molecule_id)
        .values(smiles=data.smiles)
    )
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise ValueError(
            "Molecule with this SMILES already exists") from e
    return Molecule(id=molecule_id, smiles=data.smiles)


async def delete_molecule(session: AsyncSession,
                          molecule_id: str) -> bool:
    obj = await session.get(MoleculeORM, molecule_id)
    if not obj:
        return False
    await session.execute(delete(MoleculeORM).where(
        MoleculeORM.id == molecule_id))
    await session.commit()
    return True


async def get_molecule(session: AsyncSession, molecule_id: str) -> Molecule:
    obj = await session.get(MoleculeORM, molecule_id)
    if not obj:
        return None
    return Molecule(id=obj.id, smiles=obj.smiles)
