from __future__ import annotations

import io
import re

from rdkit import Chem
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import MoleculeORM

WS = re.compile(r"\s+")


def norm_id(s: str) -> str:
    return (s or "").strip().lower()


def canon_smiles(s: str, *, validate: bool) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    if not validate:
        return s
    m = Chem.MolFromSmiles(s)
    return Chem.MolToSmiles(m, canonical=True) if m else None


async def flush_batch(
        session: AsyncSession,
        batch: list[MoleculeORM]) -> tuple[int, int, int, int]:
    added = skipped_id = skipped_smiles = invalid = 0
    if not batch:
        return 0, 0, 0, 0

    session.add_all(batch)
    try:
        await session.commit()
        return len(batch), 0, 0, 0
    except IntegrityError:
        await session.rollback()
        for obj in batch:
            try:
                session.add(obj)
                await session.commit()
                added += 1
            except IntegrityError:
                await session.rollback()
                if await session.get(MoleculeORM, obj.id):
                    skipped_id += 1
                else:
                    existed = (await session.execute(
                        select(MoleculeORM.id).where(
                            MoleculeORM.smiles == obj.smiles)
                    )).first()
                    if existed:
                        skipped_smiles += 1
                    else:
                        invalid += 1
    return added, skipped_id, skipped_smiles, invalid


async def import_uploadfile(
    session: AsyncSession,
    upload,
    *,
    batch_size: int = 1000,
    validate_smiles: bool = True,
) -> dict:
    if not getattr(upload, "filename", None):
        raise ValueError("No file provided")

    added = skipped_id = skipped_smiles = invalid = 0
    total = 0
    errors: list[dict] = []
    batch: list[MoleculeORM] = []

    try:
        upload.file.seek(0)
    except Exception:
        pass

    with io.TextIOWrapper(upload.file,
                          encoding="utf-8",
                          errors="replace") as buf:
        for line_no, raw in enumerate(buf, start=1):
            total = line_no
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            if "," in line:
                parts = [p.strip() for p in line.split(",")]
            else:
                parts = WS.split(line)
            if len(parts) < 2 or not parts[0]:
                invalid += 1
                errors.append({"line": line_no,
                               "error": "Expected: 'id,smiles' or 'id smiles'",
                               "content": raw.rstrip("\n")})
                continue

            mol_id = (parts[0])
            canon = canon_smiles(parts[1], validate=validate_smiles)

            if canon is None:
                invalid += 1
                errors.append({"line": line_no,
                               "error": "Invalid SMILES",
                               "content": raw.rstrip("\n")})
                continue

            batch.append(MoleculeORM(id=mol_id, smiles=canon))
            if len(batch) >= batch_size:
                a, ki, ks, inv = await (session, batch)
                added += a
                skipped_id += ki
                skipped_smiles += ks
                invalid += inv
                batch.clear()

    if batch:
        a, ki, ks, inv = await (session, batch)
        added += a
        skipped_id += ki
        skipped_smiles += ks
        invalid += inv

    return {
        "file": upload.filename,
        "summary": {
            "added": added,
            "skipped_id_exists": skipped_id,
            "skipped_smiles_exists": skipped_smiles,
            "invalid": invalid,
            "total_lines": total,
        },
        "errors": errors,
        "hint": "Formats: 'id,smiles' or 'id smiles'. "
        "Starting with '#' are ignored.",
    }
