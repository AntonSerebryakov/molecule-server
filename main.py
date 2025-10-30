from __future__ import annotations

import os
import io
import re
import json
from typing import Annotated, List, Optional

import logging_config


from celery.result import AsyncResult

from fastapi import (
    FastAPI,
    HTTPException,
    status,
    Depends,
    Response,
    Query,
    File,
    UploadFile,
)

from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem import rdDepictor, MolFromSmiles, MolToSmiles
from redis import asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import crud
from database import engine, Base, get_session

from models import MoleculeORM
from schemas import Molecule, MoleculeUpdate
from tasks import substructure_search_task
from celery_worker import celery as celery_app

SEARCH_CACHE_PREFIX = os.getenv("SEARCH_CACHE_PREFIX", "cache:search:")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_TTL = int(os.getenv("REDIS_TTL", "300"))

SessionDep = Annotated[AsyncSession, Depends(get_session)]

app = FastAPI(title="Molecule Server (DB, draw, file import)")
logging_config.logger.info("API starts up")


@app.on_event("startup")
async def on_startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        app.state.redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
        )
        await app.state.redis.ping()
    except Exception:
        app.state.redis = None


@app.on_event("shutdown")
async def on_shutdown() -> None:
    r: Optional[aioredis.Redis] = getattr(app.state, "redis", None)
    if r is not None:
        try:
            await r.close()
        except Exception:
            pass


def canon_smiles_or_none(s: str) -> str | None:
    s = (s or "").strip()
    mol = MolFromSmiles(s)
    if mol is None:
        return None
    return MolToSmiles(mol, canonical=True)


async def redis_clear() -> None:
    r: Optional[aioredis.Redis] = getattr(app.state, "redis", None)
    if r is not None:
        try:
            async for key in r.scan_iter(match=f"{SEARCH_CACHE_PREFIX}*"):
                await r.delete(key)
        except Exception:
            pass
    return None


@app.post("/add", response_model=Molecule,
          status_code=status.HTTP_201_CREATED)
async def create_molecule(
    body: Molecule,
    session: SessionDep,
) -> Molecule:
    try:
        molecule = await crud.create_molecule(session, body)
        await redis_clear()
        return molecule
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/list", response_model=List[Molecule])
async def list_molecules(
    session: SessionDep,
    limit: int = Query(100, ge=1, le=10_000, description="Max Mols in answer"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
) -> List[Molecule]:
    items: List[Molecule] = [m async for m in crud.iter_molecules(
        session,
        limit=limit,
        offset=offset,
        chunk_size=500,
    )]
    return items


@app.get("/molecule/{molecule_id}", response_model=Molecule)
async def get_molecule_by_id(
    molecule_id: str,
    session: SessionDep,
) -> List[Molecule]:
    result = await crud.get_molecule(session, molecule_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Molecule not found")
    return result


@app.patch("/patch/{molecule_id}", response_model=Molecule)
async def update_molecule(
    molecule_id: str,
    body: MoleculeUpdate,
    session: SessionDep,
) -> Molecule:
    result = await crud.update_molecule(session, molecule_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Molecule not found")
    return result


@app.delete(
    "/delete/{molecule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_molecule(
    molecule_id: str,
    session: SessionDep,
) -> Response:
    ok = await crud.delete_molecule(session, molecule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Molecule not found")
    await redis_clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/search/tasks")
async def substr_search(
    query: str = Query(
        ..., description="SMILES OR SMARTS"
    ),
):
    reddis_cache: Optional[aioredis.Redis] = getattr(app.state, "redis", None)
    cache_key = f"{SEARCH_CACHE_PREFIX}{query}"
    if reddis_cache is not None:
        try:
            cached = await reddis_cache.get(cache_key)
            if cached:
                data = json.loads(cached)
                return {"status": "SUCCESS", "cached": True, "result": data}
        except Exception:
            pass

    task = substructure_search_task.delay(query)
    return {"task_id": task.id, "status": task.status, "cached": False}


@app.get("/search/tasks/{task_id}")
async def get_substr_result(task_id: str):
    task = AsyncResult(task_id, app=celery_app)
    if task.state in ("PENDING", "RETRY"):
        return {"task_id": task_id, "status": task.state}
    if task.state == "STARTED":
        return {"task_id": task_id, "status": "STARTED"}
    if task.state == "FAILURE":
        return {"task_id": task_id, "status": "FAILURE",
                "error": str(task.info)}
    return {"task_id": task_id, "status": "SUCCESS", "result": task.result}


@app.post("/add/file")
async def add_from_file(session: SessionDep, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    added = 0
    skipped_id_exists = 0
    skipped_smiles_exists = 0
    invalid = 0
    errors: list[dict] = []
    total_lines = 0

    BATCH = 1000
    to_insert: list[MoleculeORM] = []
    ws = re.compile(r"\s+")

    try:
        file.file.seek(0)
    except Exception:
        pass

    with io.TextIOWrapper(file.file, encoding="utf-8", errors="replace") as b:
        for line_no, line in enumerate(b, start=1):
            total_lines = line_no
            s = line.strip()
            if not s or s.startswith("#"):
                continue

            parts = [
                p.strip() for p in s.split(",")] if "," in s else ws.split(s)
            if len(parts) < 2 or not parts[0]:
                invalid += 1
                errors.append({"line": line_no,
                               "error": "Expected: 'id,smiles' or 'id smiles'",
                               "content": line.rstrip("\n")})
                continue

            mol_id, smiles_raw = parts[0], parts[1]
            canon = (smiles_raw)
            if canon is None:
                invalid += 1
                errors.append({"line": line_no, "error": "Invalid SMILES",
                               "content": line.rstrip("\n")})
                continue

            to_insert.append(MoleculeORM(id=mol_id, smiles=canon))

            if len(to_insert) >= BATCH:
                session.add_all(to_insert)
                try:
                    await session.commit()
                    added += len(to_insert)
                    to_insert.clear()
                except IntegrityError:
                    await session.rollback()
                    for obj in to_insert:
                        try:
                            session.add(obj)
                            await session.commit()
                            added += 1
                        except IntegrityError:
                            await session.rollback()
                            if await session.get(MoleculeORM, obj.id):
                                skipped_id_exists += 1
                            else:
                                existed = (await session.execute(
                                    select(MoleculeORM.id).where(
                                        MoleculeORM.smiles == obj.smiles)
                                )).first()
                                if existed:
                                    skipped_smiles_exists += 1
                                else:
                                    invalid += 1
                    to_insert.clear()

    if to_insert:
        session.add_all(to_insert)
        try:
            await session.commit()
            added += len(to_insert)
        except IntegrityError:
            await session.rollback()
            for obj in to_insert:
                try:
                    session.add(obj)
                    await session.commit()
                    added += 1
                except IntegrityError:
                    await session.rollback()
                    if await session.get(MoleculeORM, obj.id):
                        skipped_id_exists += 1
                    else:
                        existed = (await session.execute(
                            select(MoleculeORM.id).where(
                                MoleculeORM.smiles == obj.smiles)
                        )).first()
                        if existed:
                            skipped_smiles_exists += 1
                        else:
                            invalid += 1

    if added > 0:
        await redis_clear()
    return {
        "file": file.filename,
        "summary": {
            "added": added,
            "skipped_id_exists": skipped_id_exists,
            "skipped_smiles_exists": skipped_smiles_exists,
            "invalid": invalid,
            "total_lines": total_lines,
        },
        "errors": errors,
        "hint": "Formats: 'id,smiles' or 'id smiles'. Lines with '#' ignores.",
    }


@app.get("/draw/{molecule_id}")
async def draw_molecule(
    molecule_id: str,
    session: SessionDep,
    fmt: str = Query("png", pattern="^(png|svg)$"),
    size: int = Query(300, ge=100, le=1200),
):
    obj = await session.get(MoleculeORM, molecule_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Molecule not found")

    mol = MolFromSmiles(obj.smiles)
    if mol is None:
        raise HTTPException(status_code=500, detail="Stored SMILES is invalid")

    rdDepictor.SetPreferCoordGen(True)
    rdDepictor.Compute2DCoords(mol)

    if fmt == "svg":
        drawer = rdMolDraw2D.MolDraw2DSVG(size, size)
    else:
        drawer = rdMolDraw2D.MolDraw2DCairo(size, size)

    opts = drawer.drawOptions()
    opts.useBWAtomPalette = False
    opts.addAtomIndices = True
    for a in mol.GetAtoms():
        if a.GetSymbol() == "C":
            opts.atomLabels[a.GetIdx()] = "C"

    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()

    if fmt == "svg":
        svg = drawer.GetDrawingText().encode("utf-8")
        return Response(svg, media_type="image/svg+xml")
    png = drawer.GetDrawingText()
    return Response(png, media_type="image/png")
