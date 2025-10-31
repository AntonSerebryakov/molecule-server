from fastapi import Response
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem import rdDepictor
from rdkit.Chem.rdchem import Mol


async def draw_molecule(
    mol: Mol,
    fmt: str,
    size: int,
):

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
