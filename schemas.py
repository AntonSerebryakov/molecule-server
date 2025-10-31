from pydantic import BaseModel, field_validator, ConfigDict
from rdkit import Chem


class MoleculeUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    smiles: str

    @field_validator("smiles", mode="before")
    @classmethod
    def validate_and_canonicalize(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("SMILES must be a string")
        s = v.strip()
        mol = Chem.MolFromSmiles(s)
        if mol is None:
            raise ValueError("Invalid SMILES string")
        return Chem.MolToSmiles(mol, canonical=True)


class Molecule(MoleculeUpdate):
    id: str

    @field_validator("id", mode="before")
    @classmethod
    def id_lower(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("ID must be a non-empty string")
        return v.strip().lower()
