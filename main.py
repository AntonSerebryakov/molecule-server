from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from typing import Dict
from rdkit import Chem


app = FastAPI(title="Molecule Server")


molecule_list: Dict[str, str] = {}


class MoleculeUpdate(BaseModel):
   smiles: str

   @classmethod
   @field_validator("smiles")
   def valid_smiles(cls, v:str) -> str:
       if Chem.MolFromSmiles(v) is None:
           raise ValueError("Invalid SMILES string")
       return v


class Molecule(MoleculeUpdate):
    id : str


@app.post("/add/", response_model=Molecule)
def add_molecule(molecule: Molecule):
   if molecule.id in molecule_list:
       raise HTTPException(status_code=400, detail="Molecule ID already exists")
   molecule_list[molecule.id] = molecule.smiles
   return molecule


@app.put("/add/{mol_name}", response_model=Molecule)
def update_molecule(mol_name: str, update: MoleculeUpdate):
   if mol_name not in molecule_list:
       raise HTTPException(status_code=404, detail="Molecule not found")
   molecule_list[mol_name] = update.smiles
   return {"id": mol_name, "smiles": update.smiles}


@app.delete("/add/{mol_name}")
def delete_molecule(mol_name: str):
   if mol_name not in molecule_list:
       raise HTTPException(status_code=404, detail="Molecule not found")
   del molecule_list[mol_name]
   return {"detail": f"Molecule '{mol_name}' deleted"}


@app.get("/search/")
def substructure_search(query_smiles: str):
   query_mol = Chem.MolFromSmiles(query_smiles)
   if query_mol is None:
       raise HTTPException(status_code=400, detail="Didn't found any match")

   results = []
   for id, smile in molecule_list.items():
       mol = Chem.MolFromSmiles(smile)
       if mol is not None and mol.HasSubstructMatch(query_mol):
           results.append({"id": id, "smiles": smile})

   return {"query": query_smiles, "matches": results}


if __name__ == "__main__":
   import uvicorn
   uvicorn.run("main:app", host="127.0.0.1", port=9080, reload=True)