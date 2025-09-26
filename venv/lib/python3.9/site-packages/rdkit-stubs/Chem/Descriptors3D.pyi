"""
 Descriptors derived from a molecule's 3D structure

"""
from __future__ import annotations
from rdkit.Chem.Descriptors import _isCallable
from rdkit.Chem import rdMolDescriptors
__all__: list[str] = ['CalcMolDescriptors3D', 'descList', 'rdMolDescriptors']
def CalcMolDescriptors3D(mol, confId = None):
    """
    
        Compute all 3D descriptors of a molecule
        
        Arguments:
        - mol: the molecule to work with
        - confId: conformer ID to work with. If not specified the default (-1) is used
        
        Return:
        
        dict
            A dictionary with decriptor names as keys and the descriptor values as values
    
        raises a ValueError 
            If the molecule does not have conformers
        
    """
def _setupDescriptors(namespace):
    ...
descList: list  # value = [('PMI1', <function <lambda> at 0x104f184c0>), ('PMI2', <function <lambda> at 0x107df5c10>), ('PMI3', <function <lambda> at 0x107df5ca0>), ('NPR1', <function <lambda> at 0x107df5d30>), ('NPR2', <function <lambda> at 0x107df5dc0>), ('RadiusOfGyration', <function <lambda> at 0x107df5e50>), ('InertialShapeFactor', <function <lambda> at 0x107df5ee0>), ('Eccentricity', <function <lambda> at 0x107df5f70>), ('Asphericity', <function <lambda> at 0x108230040>), ('SpherocityIndex', <function <lambda> at 0x1082300d0>), ('PBF', <function <lambda> at 0x108230160>)]
