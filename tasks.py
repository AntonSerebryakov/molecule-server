import json
import os
from rdkit import Chem
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from celery_worker import celery as celery_app
from models import MoleculeORM
import redis

SYNC_DATABASE_URL = os.getenv("SYNC_DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
REDIS_TTL = int(os.getenv("REDIS_TTL", "300"))
CACHE_PREFIX = os.getenv("SEARCH_CACHE_PREFIX", "cache:search:")

engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True)
rds = redis.from_url(REDIS_URL, decode_responses=True)


@celery_app.task(bind=True)
def substructure_search_task(self, query: str):
    qmol = Chem.MolFromSmarts(query) or Chem.MolFromSmiles(query)
    if qmol is None:
        raise ValueError("Query is not valid SMARTS/SMILES")

    matches = []
    with Session(engine) as s:
        rows = s.execute(select(MoleculeORM.id, MoleculeORM.smiles)).all()
        for mol_id, smi in rows:
            mol = Chem.MolFromSmiles(smi)
            if mol is not None and mol.HasSubstructMatch(qmol):
                matches.append({"id": mol_id, "smiles": smi})

    payload = {"query": query, "matches": matches}
    try:
        rds.setex(f"{CACHE_PREFIX}{query}", REDIS_TTL, json.dumps(payload))
    except Exception:
        pass
    return payload
