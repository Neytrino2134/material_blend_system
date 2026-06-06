import os
from pathlib import Path
import bpy
from .constants import (
    SOURCE_BLEND_FILE,
    MATERIAL_A_GROUP_NAME,
    MATERIAL_B_GROUP_NAME,
    MIX_GROUP_NAME,
    GROUP_ROLE_PROP,
    GROUP_MATERIAL_PROP,
    GROUP_NODE_ROLE_PROP,
    GROUP_NODE_MAP_PROP,
    MAP_LABELS,
    MAP_NODE_ORDER,
    NON_COLOR_MAPS,
    MATERIAL_A_PATH_PROP,
    MATERIAL_B_PATH_PROP,
    MASK_PATH_PROP,
)
from .helpers import (
    has_group_input,
    clear_nodes,
    link_if_possible,
    node_input,
    detect_map_type,
)


def append_node_group(group_name):
    group = bpy.data.node_groups.get(group_name)
    if group:
        return group
    if not SOURCE_BLEND_FILE.exists():
        return None
    with bpy.data.libraries.load(str(SOURCE_BLEND_FILE), link=False) as (data_from, data_to):
        if group_name in data_from.node_groups:
            data_to.node_groups = [group_name]
    return bpy.data.node_groups.get(group_name)


def unique_group_copy(base_name, mat, role):
    base = append_node_group(base_name)
    if not base:
        return None
    copy = base.copy()
    copy.name = f"{mat.name}_{base_name}"
    copy[GROUP_ROLE_PROP] = role
    copy[GROUP_MATERIAL_PROP] = mat.name
    return copy


def create_group_node(tree, group_tree, name, location):
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group_tree
    node.name = name
    node.label = name
    node.location = location
    return node


def setup_nodes(mat):
    mat.use_nodes = True
    tree = mat.node_tree
    clear_nodes(tree)

    material_a = unique_group_copy(MATERIAL_A_GROUP_NAME, mat, "A")
    material_b = unique_group_copy(MATERIAL_B_GROUP_NAME, mat, "B")
    mix_group = unique_group_copy(MIX_GROUP_NAME, mat, "MIX")
    if not material_a or not material_b or not mix_group:
        missing = [name for name in (MATERIAL_A_GROUP_NAME, MATERIAL_B_GROUP_NAME, MIX_GROUP_NAME) if not append_node_group(name)]
        raise RuntimeError("Missing node groups: " + ", ".join(missing))

    nodes = tree.nodes
    links = tree.links

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-1200, 120)

    # Individual mapping for A
    mapping_a = nodes.new("ShaderNodeMapping")
    mapping_a.name = "Mapping A"
    mapping_a.label = "Mapping Material A"
    mapping_a.location = (-950, 220)
    
    # Individual mapping for B
    mapping_b = nodes.new("ShaderNodeMapping")
    mapping_b.name = "Mapping B"
    mapping_b.label = "Mapping Material B"
    mapping_b.location = (-950, -140)

    a_node = create_group_node(tree, material_a, "Material A", (-600, 220))
    b_node = create_group_node(tree, material_b, "Material B", (-600, -140))
    
    # Ensure "Vector" input exists in groups A and B
    for grp_tree in (material_a, material_b):
        if not has_group_input(grp_tree, "Vector"):
            if hasattr(grp_tree, "interface"):
                grp_tree.interface.new_socket(name="Vector", in_out='INPUT', socket_type='NodeSocketVector')
            else:
                grp_tree.inputs.new("NodeSocketVector", "Vector")

    links.new(texcoord.outputs["UV"], mapping_a.inputs["Vector"])
    links.new(texcoord.outputs["UV"], mapping_b.inputs["Vector"])
    links.new(mapping_a.outputs["Vector"], a_node.inputs["Vector"])
    links.new(mapping_b.outputs["Vector"], b_node.inputs["Vector"])

    mix_node = create_group_node(tree, mix_group, "Mix Material", (-120, 40))
    mix_node[GROUP_NODE_ROLE_PROP] = "MIX"

    ao_multiply = nodes.new("ShaderNodeMix")
    ao_multiply.name = "Apply AO"
    ao_multiply.label = "Apply AO"
    ao_multiply.data_type = "RGBA"
    ao_multiply.factor_mode = "UNIFORM"
    ao_multiply.blend_type = "MULTIPLY"
    ao_multiply.inputs[0].default_value = 1.0
    ao_multiply.location = (180, 140)

    normal = nodes.new("ShaderNodeNormalMap")
    normal.location = (180, -120)
    displacement = nodes.new("ShaderNodeDisplacement")
    displacement.location = (180, -330)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (480, 70)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (760, 70)

    map_mix_inputs = {
        "Base Color": ("Base Color A", "Base Color B"),
        "AO": ("AO  A", "AO B"),
        "Metallic": ("Metallic A", "Metallic B"),
        "Roughness": ("Roughness A", "Roughness B"),
        "Alpha": ("Alpha A", "Alpha B"),
        "Normal": ("Normal A", "Normal B"),
        "Displacement": ("Displacement A", "Displacement B"),
        "Emission Color": ("Emission Color A", "Emission Color B"),
        "Emission Strength": ("Emission Strength A", "Emission Strength B"),
    }
    for output_name, (input_a, input_b) in map_mix_inputs.items():
        link_if_possible(tree, a_node.outputs.get(output_name), mix_node.inputs.get(input_a))
        link_if_possible(tree, b_node.outputs.get(output_name), mix_node.inputs.get(input_b))

    link_if_possible(tree, mix_node.outputs.get("Base Color"), ao_multiply.inputs[6])
    link_if_possible(tree, mix_node.outputs.get("AO"), ao_multiply.inputs[7])
    link_if_possible(tree, ao_multiply.outputs[2], node_input(bsdf, "Base Color"))
    link_if_possible(tree, mix_node.outputs.get("Metallic"), node_input(bsdf, "Metallic"))
    link_if_possible(tree, mix_node.outputs.get("Roughness"), node_input(bsdf, "Roughness"))
    link_if_possible(tree, mix_node.outputs.get("Alpha"), node_input(bsdf, "Alpha"))
    link_if_possible(tree, mix_node.outputs.get("Normal"), normal.inputs.get("Color"))
    link_if_possible(tree, normal.outputs.get("Normal"), node_input(bsdf, "Normal"))
    link_if_possible(tree, mix_node.outputs.get("Displacement"), displacement.inputs.get("Height"))
    link_if_possible(tree, displacement.outputs.get("Displacement"), output.inputs.get("Displacement"))
    link_if_possible(tree, mix_node.outputs.get("Emission Color"), node_input(bsdf, "Emission Color", "Emission"))
    link_if_possible(tree, mix_node.outputs.get("Emission Strength"), node_input(bsdf, "Emission Strength"))
    link_if_possible(tree, bsdf.outputs.get("BSDF"), output.inputs.get("Surface"))

    mat.blend_method = "BLEND"
    mat[MATERIAL_A_PATH_PROP] = ""
    mat[MATERIAL_B_PATH_PROP] = ""
    mat[MASK_PATH_PROP] = ""
    return mat


def find_group_node(mat, role):
    if not mat or not mat.use_nodes:
        return None
    for node in mat.node_tree.nodes:
        if node.bl_idname == "ShaderNodeGroup":
            if role == "MIX" and (node.name.startswith("Mix Material") or node.get(GROUP_NODE_ROLE_PROP) == "MIX"):
                return node
            if node.node_tree and node.node_tree.get(GROUP_ROLE_PROP) == role:
                return node
    return None


def group_has_any_images(group_tree):
    if not group_tree:
        return False
    return any(node.bl_idname == "ShaderNodeTexImage" and node.image for node in group_tree.nodes)


def auto_slot(mat):
    a_node = find_group_node(mat, "A")
    b_node = find_group_node(mat, "B")
    if a_node and not group_has_any_images(a_node.node_tree):
        return "A"
    if b_node and not group_has_any_images(b_node.node_tree):
        return "B"
    return None


def image_colorspace(image, map_type):
    if map_type in NON_COLOR_MAPS:
        image.colorspace_settings.name = "Non-Color"
    else:
        image.colorspace_settings.name = "sRGB"


def clear_group_texture_nodes(group_tree):
    for node in list(group_tree.nodes):
        if node.bl_idname == "ShaderNodeTexImage":
            group_tree.nodes.remove(node)


def get_or_create_texture_node(group_tree, map_type):
    wanted = MAP_LABELS[map_type]
    for node in group_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and node.get(GROUP_NODE_MAP_PROP) == map_type:
            return node
    for node in group_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and not node.image:
            node[GROUP_NODE_MAP_PROP] = map_type
            node.label = wanted
            node.name = wanted
            return node
    node = group_tree.nodes.new("ShaderNodeTexImage")
    node[GROUP_NODE_MAP_PROP] = map_type
    node.label = wanted
    node.name = wanted
    return node


def ensure_internal_mapping(group_tree):
    texcoord = next((n for n in group_tree.nodes if n.bl_idname == "ShaderNodeTexCoord"), None)
    mapping = next((n for n in group_tree.nodes if n.bl_idname == "ShaderNodeMapping"), None)
    if not texcoord:
        texcoord = group_tree.nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-1200, 0)
    if not mapping:
        mapping = group_tree.nodes.new("ShaderNodeMapping")
        mapping.location = (-1000, 0)
    if not mapping.inputs["Vector"].is_linked:
        group_tree.links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])
    
    # Ensure all texture nodes are connected to this mapping
    for node in group_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage":
            # If not linked to anything, or linked to something that's NOT the group input, link to mapping
            if not node.inputs["Vector"].is_linked or (node.inputs["Vector"].links and node.inputs["Vector"].links[0].from_node.bl_idname != "NodeGroupInput"):
                group_tree.links.new(mapping.outputs["Vector"], node.inputs["Vector"])
    return mapping


def output_socket_name(map_type):
    return MAP_LABELS[map_type]


def connect_texture_node(group_tree, tex_node, map_type):
    # Check if there's an external "Vector" input connected to this group
    group_input = next((n for n in group_tree.nodes if n.bl_idname == "NodeGroupInput"), None)
    vector_out = group_input.outputs.get("Vector") if group_input else None
    
    if vector_out and vector_out.is_linked:
        # If external vector is used, connect texture directly to it
        group_tree.links.new(vector_out, tex_node.inputs["Vector"])
    else:
        # Otherwise use internal mapping
        mapping = ensure_internal_mapping(group_tree)
        if not tex_node.inputs["Vector"].is_linked:
            group_tree.links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

    out_node = next((n for n in group_tree.nodes if n.bl_idname == "NodeGroupOutput" and n.is_active_output), None)
    if not out_node:
        out_node = next((n for n in group_tree.nodes if n.bl_idname == "NodeGroupOutput"), None)
    if not out_node:
        return

    target = out_node.inputs.get(output_socket_name(map_type))
    if not target:
        return
    for link in list(target.links):
        group_tree.links.remove(link)
    source = tex_node.outputs.get("Color")
    if map_type == "alpha":
        source = tex_node.outputs.get("Alpha")
    if source:
        group_tree.links.new(source, target)


def arrange_texture_nodes(group_tree):
    x = -760
    y = 420
    for index, map_type in enumerate(MAP_NODE_ORDER):
        for node in group_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.get(GROUP_NODE_MAP_PROP) == map_type:
                node.location = (x, y - index * 260)
                node.width = 260
    for node in group_tree.nodes:
        if node.bl_idname == "ShaderNodeMapping":
            node.location = (-1040, 40)
        elif node.bl_idname == "ShaderNodeTexCoord":
            node.location = (-1280, 40)
        elif node.bl_idname == "NodeGroupOutput":
            node.location = (-260, 40)


def load_textures_into_slot(mat, slot, filepaths, replace=True):
    group_node = find_group_node(mat, slot)
    if not group_node:
        raise RuntimeError(f"Material {slot} group is missing. Run Create Blend Material first.")
    group_tree = group_node.node_tree
    if replace:
        clear_group_texture_nodes(group_tree)

    # 1. Identify types for all files
    typed_files = {}  # map_type -> list of filepaths
    unidentified = []

    for fp in filepaths:
        mtype = detect_map_type(fp)
        if mtype:
            typed_files.setdefault(mtype, []).append(fp)
        else:
            unidentified.append(fp)

    # 2. Fallback for unidentified files (e.g., Metal055A.png -> Base Color)
    if unidentified and "base_color" not in typed_files:
        # Heuristic: the one with the shortest name is likely the main base color
        unidentified.sort(key=len)
        typed_files["base_color"] = [unidentified[0]]

    # 3. For each type, pick the BEST file
    final_files = {}
    for mtype, files in typed_files.items():
        if len(files) == 1:
            final_files[mtype] = files[0]
        else:
            if mtype == "normal":
                # Prefer GL over DX
                gl_files = [f for f in files if "gl" in f.lower()]
                final_files[mtype] = gl_files[0] if gl_files else files[0]
            elif mtype == "height":
                # Prefer displacement over height/bump
                disp_files = [f for f in files if "disp" in f.lower()]
                final_files[mtype] = disp_files[0] if disp_files else files[0]
            else:
                final_files[mtype] = files[0]

    loaded = []
    folder = ""
    for map_type, filepath in final_files.items():
        image = bpy.data.images.load(filepath, check_existing=True)
        image_colorspace(image, map_type)
        tex_node = get_or_create_texture_node(group_tree, map_type)
        tex_node.image = image
        tex_node[GROUP_NODE_MAP_PROP] = map_type
        connect_texture_node(group_tree, tex_node, map_type)
        loaded.append(map_type)
        folder = str(Path(filepath).parent)

    arrange_texture_nodes(group_tree)
    if folder:
        mat[MATERIAL_A_PATH_PROP if slot == "A" else MATERIAL_B_PATH_PROP] = folder
    return loaded


def create_mask(mat):
    mix_node = find_group_node(mat, "MIX")
    if not mix_node:
        raise RuntimeError("Mix Material group is missing. Run Create Blend Material first.")
    tree = mat.node_tree

    # Create black image
    img_name = f"{mat.name}_Mask"
    image = bpy.data.images.new(img_name, width=2048, height=2048)
    image.generated_color = (0, 0, 0, 1)
    image_colorspace(image, "mask")

    tex = next((n for n in tree.nodes if n.get(GROUP_NODE_MAP_PROP) == "mask"), None)
    if not tex:
        tex = tree.nodes.new("ShaderNodeTexImage")
        tex.name = "Blend Mask"
        tex.label = "Blend Mask"
        tex[GROUP_NODE_MAP_PROP] = "mask"

    tex.image = image
    tex.location = (-460, -430)

    # Add mapping for the mask
    texcoord = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeTexCoord"), None)
    if not texcoord:
        texcoord = tree.nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-900, -430)

    # Use a dedicated mapping node for the mask to allow independent control
    mapping = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeMapping" and any(l.to_node == tex for l in n.outputs[0].links)), None)
    if not mapping:
        mapping = tree.nodes.new("ShaderNodeMapping")
        mapping.location = (-680, -430)

    tree.links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])

    target = mix_node.inputs.get("Mix (Factor) A+B")
    if target:
        for link in list(target.links):
            tree.links.remove(link)
        tree.links.new(tex.outputs["Color"], target)
    return image


def reload_slot(mat, slot):
    group_node = find_group_node(mat, slot)
    if not group_node:
        return 0
    count = 0
    for node in group_node.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and node.image:
            node.image.reload()
            count += 1
    return count
