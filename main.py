from __future__ import annotations

import json
import os
from typing import Annotated, List, Optional

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
from rdkit.Chem import MolFromSmiles
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

import logging_config


import crud
from database import engine, Base, get_session
from utils import import_uploadfile, canon_smiles
from models import MoleculeORM
from schemas import Molecule, MoleculeUpdate
from tasks import substructure_search_task
from celery_worker import celery as celery_app
from draw import draw_molecule

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
    try:
        loaded = await import_uploadfile(
            session,
            file,
            batch_size=1000,
            validate_smiles=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if loaded["summary"]["added"] > 0:
        await redis_clear()

    return loaded


@app.get("/draw_by_id/{molecule_id}")
async def draw_molecule_by_id(
    molecule_id: str,
    session: SessionDep,
    fmt: str = Query("png", pattern="^(png|svg)$"),
    size: int = Query(300, ge=100, le=1200),
):
    molecule_id = molecule_id.lower()
    obj = await session.get(MoleculeORM, molecule_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Molecule not found")

    mol = MolFromSmiles(obj.smiles)
    result = await draw_molecule(mol=mol, fmt=fmt, size=size)
    return result


@app.get("/draw_by_smiles")
async def draw_molecule_by_smyle(
    smile: str = Query(),
    fmt: str = Query("png", pattern="^(png|svg)$"),
    size: int = Query(300, ge=100, le=1200),
):
    smile = canon_smiles(smile, validate=True)
    if not smile:
        raise HTTPException(status_code=400, detail="Invalid SMILES format")
    mol = MolFromSmiles(smile)
    result = await draw_molecule(mol=mol, fmt=fmt, size=size)
    return result
