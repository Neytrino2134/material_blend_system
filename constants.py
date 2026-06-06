from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = ADDON_DIR / "resources"
SOURCE_BLEND_FILE = RESOURCES_DIR / "Mix Materal Shader.blend"

MATERIAL_A_GROUP_NAME = "Material A"
MATERIAL_B_GROUP_NAME = "Material B"
MIX_GROUP_NAME = "Mix Material"
DEFAULT_MATERIAL_NAME = "Blend Material"

MATERIAL_A_PATH_PROP = "blend_material_a_path"
MATERIAL_B_PATH_PROP = "blend_material_b_path"
MASK_PATH_PROP = "blend_material_mask_path"

GROUP_ROLE_PROP = "blend_material_group_role"
GROUP_MATERIAL_PROP = "blend_material_owner"
GROUP_NODE_ROLE_PROP = "blend_material_node_role"
GROUP_NODE_MAP_PROP = "blend_material_map_type"

MAP_TAGS = {
    "base_color": ("basecolor", "base_color", "albedo", "diffuse", "color", "col", "alb"),
    "roughness": ("roughness", "rough", "rgh", "gloss", "glossiness"),
    "metallic": ("metallic", "metal", "metalness", "mtl", "met"),
    "normal": ("normal", "nor", "nrm", "normalgl", "normaldx", "nm"),
    "ao": ("ambientocclusion", "occlusion", "ao", "occ"),
    "height": ("displacement", "height", "disp", "bump", "hgt"),
    "alpha": ("opacity", "alpha", "mask", "opac"),
    "emission_color": ("emission", "emissive", "em", "emit"),
    "emission_strength": ("emission_strength", "emissionscale", "emitstrength", "emstrength"),
}

MAP_LABELS = {
    "base_color": "Base Color",
    "ao": "AO",
    "metallic": "Metallic",
    "roughness": "Roughness",
    "alpha": "Alpha",
    "normal": "Normal",
    "height": "Displacement",
    "emission_color": "Emission Color",
    "emission_strength": "Emission Strength",
}

MAP_NODE_ORDER = ("base_color", "ao", "roughness", "metallic", "normal", "height", "alpha", "emission_color", "emission_strength")
NON_COLOR_MAPS = {"ao", "roughness", "metallic", "normal", "height", "alpha", "mask", "emission_strength"}
