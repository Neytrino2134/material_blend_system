bl_info = {
    "name": "Material Blend System",
    "author": "Codex",
    "version": (0, 1, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Material Blend",
    "description": "Mix two PBR texture sets through one material mask without Mix Shader.",
    "category": "Material",
}

import os
import re
from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ImportHelper


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

keymaps = []


MAP_TAGS = {
    "base_color": ("basecolor", "base_color", "albedo", "diffuse", "color", "col", "alb"),
    "roughness": ("roughness", "rough", "rgh", "gloss", "glossiness"),
    "metallic": ("metallic", "metal", "metalness", "mtl", "met"),
    "normal": ("normal", "nor", "nrm", "normalgl", "normaldx", "nm"),
    "ao": ("ambientocclusion", "occlusion", "ao", "occ"),
    "height": ("displacement", "height", "disp", "bump", "hgt"),
    "alpha": ("opacity", "alpha", "mask", "opac"),
}

MAP_LABELS = {
    "base_color": "Base Color",
    "ao": "AO",
    "metallic": "Metallic",
    "roughness": "Roughness",
    "alpha": "Alpha",
    "normal": "Normal",
    "height": "Displacement",
}

MAP_NODE_ORDER = ("base_color", "ao", "roughness", "metallic", "normal", "height", "alpha")
NON_COLOR_MAPS = {"ao", "roughness", "metallic", "normal", "height", "alpha", "mask"}


def normalize_name(value):
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def detect_map_type(filepath):
    stem = Path(filepath).stem.lower()
    parts = re.split(r"[^a-z0-9]", stem)

    # 1. Try exact part match (strongest)
    for map_type, tags in MAP_TAGS.items():
        for tag in tags:
            if tag.lower() in parts:
                return map_type

    # 2. Try normalized endswith match (for things like NormalGL without separator)
    stem_norm = normalize_name(stem)
    for map_type, tags in MAP_TAGS.items():
        for tag in tags:
            tag_norm = normalize_name(tag)
            # Use a minimum length to avoid matching very short tags like 'ao' or 'nm' accidentally
            if len(tag_norm) > 3 and stem_norm.endswith(tag_norm):
                return map_type

    return None


def active_material(context):
    obj = context.object
    if obj and obj.active_material:
        return obj.active_material
    return None


def ensure_material(context):
    obj = context.object
    if not obj:
        return None
    mat = obj.active_material
    if mat is None:
        mat = bpy.data.materials.new(DEFAULT_MATERIAL_NAME)
        obj.data.materials.append(mat)
        obj.active_material = mat
    mat.use_nodes = True
    return mat


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


def node_input(node, *names):
    for name in names:
        sock = node.inputs.get(name)
        if sock:
            return sock
    return None


def node_output(node, *names):
    for name in names:
        sock = node.outputs.get(name)
        if sock:
            return sock
    return None


def link_if_possible(tree, out_socket, in_socket):
    if out_socket and in_socket:
        tree.links.new(out_socket, in_socket)
        return True
    return False


def clear_nodes(tree):
    for node in list(tree.nodes):
        tree.nodes.remove(node)


def create_group_node(tree, group_tree, name, location):
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group_tree
    node.name = name
    node.label = name
    node.location = location
    return node


def iter_group_interface_items(tree):
    interface = getattr(tree, "interface", None)
    if not interface:
        return ()

    items = getattr(interface, "items_tree", None)
    if items is None:
        items = getattr(interface, "items", ())
        if callable(items):
            items = items()
    return items


def has_group_input(tree, name):
    if hasattr(tree, "interface"):
        return any(
            item.name == name
            for item in iter_group_interface_items(tree)
            if getattr(item, "item_type", None) == 'SOCKET' and getattr(item, "in_out", None) == 'INPUT'
        )
    return name in tree.inputs


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


def material_folder(mat, slot):
    prop = MATERIAL_A_PATH_PROP if slot == "A" else MATERIAL_B_PATH_PROP
    value = mat.get(prop, "")
    return value if value and os.path.isdir(value) else ""


def selected_mix_group_node(context):
    if context.area and context.area.type != "NODE_EDITOR":
        return False
    node = getattr(context, "active_node", None)
    return bool(
        node
        and node.bl_idname == "ShaderNodeGroup"
        and (
            node.get(GROUP_NODE_ROLE_PROP) == "MIX"
            or node.name.startswith("Mix Material")
            or (node.node_tree and node.node_tree.name.startswith(MIX_GROUP_NAME))
        )
    )


class MBS_OT_create_blend_material(Operator):
    bl_idname = "mbs.create_blend_material"
    bl_label = "Create Blend Material"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mat = ensure_material(context)
        if not mat:
            self.report({"ERROR"}, "Select an object first.")
            return {"CANCELLED"}
        try:
            setup_nodes(mat)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created {mat.name}")
        return {"FINISHED"}


class MBS_OT_load_material_textures(Operator, ImportHelper):
    bl_idname = "mbs.load_material_textures"
    bl_label = "Load Blend Material Textures"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.exr;*.bmp;*.tga", options={"HIDDEN"})
    slot: EnumProperty(
        name="Material Slot",
        items=(("AUTO", "Auto", ""), ("A", "Material A", ""), ("B", "Material B", "")),
        default="AUTO",
    )
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)

    def invoke(self, context, event):
        mat = active_material(context)
        if not mat:
            self.report({"ERROR"}, "Select an object with a blend material.")
            return {"CANCELLED"}
        if self.slot == "AUTO":
            slot = auto_slot(mat)
            if slot is None:
                return bpy.ops.mbs.choose_replace_slot("INVOKE_DEFAULT")
            self.slot = slot
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        mat = active_material(context)
        if not mat:
            self.report({"ERROR"}, "Select an object with a blend material.")
            return {"CANCELLED"}
        directory = Path(self.filepath).parent
        filepaths = [str(directory / f.name) for f in self.files] if self.files else [self.filepath]
        slot = self.slot if self.slot in {"A", "B"} else auto_slot(mat)
        if slot is None:
            self.report({"ERROR"}, "Both slots are filled. Use Load Material A or Load Material B.")
            return {"CANCELLED"}
        loaded = load_textures_into_slot(mat, slot, filepaths, replace=True)
        if not loaded:
            self.report({"WARNING"}, "No recognized PBR texture names were selected.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Loaded {len(loaded)} maps into Material {slot}.")
        return {"FINISHED"}


class MBS_OT_choose_replace_slot(Operator):
    bl_idname = "mbs.choose_replace_slot"
    bl_label = "Replace Filled Slot"
    bl_options = {"REGISTER", "UNDO"}

    slot: EnumProperty(
        name="Replace",
        items=(("A", "Replace Material A", ""), ("B", "Replace Material B", ""), ("CANCEL", "Cancel", "")),
        default="A",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if self.slot == "CANCEL":
            return {"CANCELLED"}
        bpy.ops.mbs.load_material_textures("INVOKE_DEFAULT", slot=self.slot)
        return {"FINISHED"}


class MBS_OT_create_blend_mask(Operator):
    bl_idname = "mbs.create_blend_mask"
    bl_label = "Create Blend Mask"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mat = active_material(context)
        if not mat:
            self.report({"ERROR"}, "Select an object with a blend material.")
            return {"CANCELLED"}
        try:
            create_mask(mat)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Created blend mask.")
        return {"FINISHED"}


class MBS_OT_hotkey_load_material_textures(Operator):
    bl_idname = "mbs.hotkey_load_material_textures"
    bl_label = "Load Blend Material Textures"

    @classmethod
    def poll(cls, context):
        return selected_mix_group_node(context)

    def execute(self, context):
        return bpy.ops.mbs.load_material_textures("INVOKE_DEFAULT", slot="AUTO")


class MBS_OT_hotkey_create_mask(Operator):
    bl_idname = "mbs.hotkey_create_blend_mask"
    bl_label = "Create Blend Mask"

    @classmethod
    def poll(cls, context):
        return selected_mix_group_node(context)

    def execute(self, context):
        return bpy.ops.mbs.create_blend_mask("EXEC_DEFAULT")


class MBS_OT_reload_material(Operator):
    bl_idname = "mbs.reload_material"
    bl_label = "Reload Textures"
    bl_options = {"REGISTER", "UNDO"}

    slot: EnumProperty(items=(("A", "Material A", ""), ("B", "Material B", ""), ("ALL", "All", "")), default="ALL")

    def execute(self, context):
        mat = active_material(context)
        if not mat:
            self.report({"ERROR"}, "Select an object with a blend material.")
            return {"CANCELLED"}
        count = 0
        if self.slot in {"A", "ALL"}:
            count += reload_slot(mat, "A")
        if self.slot in {"B", "ALL"}:
            count += reload_slot(mat, "B")
        mask_path = mat.get(MASK_PATH_PROP, "")
        if self.slot == "ALL" and mask_path:
            for image in bpy.data.images:
                if bpy.path.abspath(image.filepath) == bpy.path.abspath(mask_path):
                    image.reload()
                    count += 1
        self.report({"INFO"}, f"Reloaded {count} images.")
        return {"FINISHED"}


class MBS_OT_open_material_folder(Operator):
    bl_idname = "mbs.open_material_folder"
    bl_label = "Open Material Folder"

    slot: EnumProperty(items=(("A", "Material A", ""), ("B", "Material B", "")), default="A")

    def execute(self, context):
        mat = active_material(context)
        folder = material_folder(mat, self.slot) if mat else ""
        if not folder:
            self.report({"ERROR"}, f"Material {self.slot} folder is not stored.")
            return {"CANCELLED"}
        os.startfile(folder)
        return {"FINISHED"}


class MBS_OT_save_preset(Operator):
    bl_idname = "mbs.save_preset"
    bl_label = "Save Preset"
    bl_options = {"REGISTER", "UNDO"}

    preset_name: StringProperty(name="Preset Name", default="Rock")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        mat = active_material(context)
        if not mat:
            self.report({"ERROR"}, "Select an object with a blend material.")
            return {"CANCELLED"}
        library = bpy.data.collections.get("Material Library") or bpy.data.collections.new("Material Library")
        if library.name not in context.scene.collection.children.keys():
            try:
                context.scene.collection.children.link(library)
            except RuntimeError:
                pass
        preset = mat.copy()
        preset.name = self.preset_name
        preset[MATERIAL_A_PATH_PROP] = mat.get(MATERIAL_A_PATH_PROP, "")
        preset[MATERIAL_B_PATH_PROP] = mat.get(MATERIAL_B_PATH_PROP, "")
        preset[MASK_PATH_PROP] = mat.get(MASK_PATH_PROP, "")
        marker = bpy.data.objects.new(self.preset_name, None)
        marker.empty_display_type = "PLAIN_AXES"
        marker.hide_viewport = True
        marker.hide_render = True
        marker["material_preset"] = preset.name
        library.objects.link(marker)
        self.report({"INFO"}, f"Saved material preset {preset.name}.")
        return {"FINISHED"}


class MBS_PT_material_blend(Panel):
    bl_label = "Material Blend"
    bl_idname = "MBS_PT_material_blend"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Material Blend"

    @classmethod
    def poll(cls, context):
        return context.space_data.type == "NODE_EDITOR" and context.space_data.tree_type == "ShaderNodeTree"

    def draw(self, context):
        layout = self.layout
        mat = active_material(context)

        layout.operator("mbs.create_blend_material", icon="MATERIAL")
        layout.separator()

        col = layout.column(align=True)
        op = col.operator("mbs.load_material_textures", text="Load Material A", icon="FILE_FOLDER")
        op.slot = "A"
        op = col.operator("mbs.load_material_textures", text="Load Material B", icon="FILE_FOLDER")
        op.slot = "B"
        layout.operator("mbs.create_blend_mask", icon="IMAGE_DATA")
        
        layout.separator()
        
        # New options section
        node = context.active_node
        is_material_group = node and node.bl_idname == "ShaderNodeGroup" and node.node_tree and node.node_tree.get(GROUP_ROLE_PROP) in {"A", "B"}
        
        box = layout.box()
        box.label(text="Selected Group Options", icon="NODETREE")
        if is_material_group:
            box.label(text=f"Group: {node.label}")
            row = box.row(align=True)
            row.operator("mbs.preview_material", text="Preview").mode = "PREVIEW"
            row.operator("mbs.preview_material", text="Reset").mode = "RESET"
            
            row = box.row(align=True)
            row.operator("mbs.toggle_mapping", text="External Mapping").mode = "EXTERNAL"
            row.operator("mbs.toggle_mapping", text="Internal Mapping").mode = "INTERNAL"
        else:
            box.label(text="Select Material A or B node", icon="INFO")

        layout.separator()

        row = layout.row(align=True)
        op = row.operator("mbs.reload_material", text="Reload A", icon="FILE_REFRESH")
        op.slot = "A"
        op = row.operator("mbs.reload_material", text="Reload B", icon="FILE_REFRESH")
        op.slot = "B"
        op = layout.operator("mbs.reload_material", text="Reload Textures", icon="FILE_REFRESH")
        op.slot = "ALL"

        row = layout.row(align=True)
        op = row.operator("mbs.open_material_folder", text="Open A", icon="FILE_FOLDER")
        op.slot = "A"
        op = row.operator("mbs.open_material_folder", text="Open B", icon="FILE_FOLDER")
        op.slot = "B"

        layout.separator()
        layout.operator("mbs.save_preset", icon="PRESET")

        if mat:
            box = layout.box()
            box.label(text=mat.name, icon="MATERIAL_DATA")
            box.label(text=f"A: {mat.get(MATERIAL_A_PATH_PROP, '') or '-'}")
            box.label(text=f"B: {mat.get(MATERIAL_B_PATH_PROP, '') or '-'}")


class MBS_OT_preview_material(Operator):
    bl_idname = "mbs.preview_material"
    bl_label = "Preview Selected Material"
    bl_description = "Preview selected material group or reset to mix"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(items=(("PREVIEW", "Preview", ""), ("RESET", "Reset", "")), default="PREVIEW")

    @classmethod
    def poll(cls, context):
        mat = active_material(context)
        return mat is not None and mat.node_tree is not None

    def execute(self, context):
        mat = active_material(context)
        tree = mat.node_tree
        nodes = tree.nodes
        links = tree.links

        output_node = next((n for n in nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None)
        if not output_node:
            self.report({"ERROR"}, "No Output Material node found.")
            return {"CANCELLED"}

        mix_node = find_group_node(mat, "MIX")
        bsdf_node = next((n for n in nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)

        if self.mode == "RESET":
            if not mix_node or not bsdf_node:
                self.report({"ERROR"}, "Mix node or BSDF node missing.")
                return {"CANCELLED"}
            
            ao_mix = next((n for n in nodes if n.label == "Apply AO"), None)
            normal_node = next((n for n in nodes if n.bl_idname == "ShaderNodeNormalMap"), None)
            disp_node = next((n for n in nodes if n.bl_idname == "ShaderNodeDisplacement"), None)

            links.new(mix_node.outputs["Base Color"], ao_mix.inputs[6] if ao_mix else bsdf_node.inputs["Base Color"])
            if ao_mix:
                links.new(mix_node.outputs["AO"], ao_mix.inputs[7])
            
            links.new(mix_node.outputs["Metallic"], bsdf_node.inputs["Metallic"])
            links.new(mix_node.outputs["Roughness"], bsdf_node.inputs["Roughness"])
            links.new(mix_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
            
            if normal_node:
                links.new(mix_node.outputs["Normal"], normal_node.inputs["Color"])
            if disp_node:
                links.new(mix_node.outputs["Displacement"], disp_node.inputs["Height"])

            if output_node:
                links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])
            
            self.report({"INFO"}, "Reset to Mix Material")
            return {"FINISHED"}

        node = context.active_node
        if not (node and node.bl_idname == "ShaderNodeGroup"):
            return {"CANCELLED"}

        # Direct connection from group outputs to a temporary Principled BSDF or just link outputs
        # To keep it simple and consistent with how the mix works, let's just swap what's connected to the main BSDF
        # or better: bypass the mix node.
        
        map_mix_inputs = {
            "Base Color": "Base Color",
            "AO": "AO", # Wait, the main BSDF doesn't have AO, it's multiplied in setup_nodes
            "Metallic": "Metallic",
            "Roughness": "Roughness",
            "Alpha": "Alpha",
            "Normal": "Normal",
            "Displacement": "Displacement",
        }

        # If we want a CLEAN preview, we should probably connect the group node's outputs 
        # to the main BSDF's inputs directly.
        
        # But wait, setup_nodes already has all that logic. 
        # Let's find the main BSDF and connect the selected node to it.
        
        if not bsdf_node:
            self.report({"ERROR"}, "No Principled BSDF node found.")
            return {"CANCELLED"}

        # Disconnect all from BSDF first? links.new will replace existing links on inputs.
        
        # Base Color logic with AO
        ao_mix = next((n for n in nodes if n.label == "Apply AO"), None)
        
        links.new(node.outputs["Base Color"], ao_mix.inputs[6] if ao_mix else bsdf_node.inputs["Base Color"])
        if ao_mix:
            links.new(node.outputs["AO"], ao_mix.inputs[7])
        
        links.new(node.outputs["Metallic"], bsdf_node.inputs["Metallic"])
        links.new(node.outputs["Roughness"], bsdf_node.inputs["Roughness"])
        links.new(node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
        
        # Normal
        normal_node = next((n for n in nodes if n.bl_idname == "ShaderNodeNormalMap"), None)
        if normal_node:
            links.new(node.outputs["Normal"], normal_node.inputs["Color"])
            
        # Displacement
        disp_node = next((n for n in nodes if n.bl_idname == "ShaderNodeDisplacement"), None)
        if disp_node:
            links.new(node.outputs["Displacement"], disp_node.inputs["Height"])

        self.report({"INFO"}, f"Previewing {node.label}")
        return {"FINISHED"}


class MBS_OT_toggle_mapping(Operator):
    bl_idname = "mbs.toggle_mapping"
    bl_label = "Toggle External Mapping"
    bl_description = "Move mapping nodes outside or inside the selected group"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(items=(("EXTERNAL", "External", ""), ("INTERNAL", "Internal", "")), default="EXTERNAL")

    @classmethod
    def poll(cls, context):
        mat = active_material(context)
        if not mat or not mat.node_tree:
            return False
        node = context.active_node
        if node and node.bl_idname == "ShaderNodeGroup" and node.node_tree:
            role = node.node_tree.get(GROUP_ROLE_PROP)
            return role in {"A", "B"}
        return False

    def execute(self, context):
        mat = active_material(context)
        node = context.active_node
        group_tree = node.node_tree
        tree = mat.node_tree

        if self.mode == "EXTERNAL":
            # 1. Ensure "Vector" input exists in group
            if not has_group_input(group_tree, "Vector"):
                if hasattr(group_tree, "interface"):
                    group_tree.interface.new_socket(name="Vector", in_out='INPUT', socket_type='NodeSocketVector')
                else:
                    group_tree.inputs.new("NodeSocketVector", "Vector")
            
            # 2. Inside group: connect Vector input to Mapping/Textures
            mapping = ensure_internal_mapping(group_tree)
            group_input = next((n for n in group_tree.nodes if n.bl_idname == "NodeGroupInput"), None)
            if group_input:
                group_tree.links.new(group_input.outputs["Vector"], mapping.inputs["Vector"])

            # 3. Outside group: create/connect mapping nodes
            texcoord = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeTexCoord"), None)
            if not texcoord:
                texcoord = tree.nodes.new("ShaderNodeTexCoord")
                texcoord.location = (node.location.x - 600, node.location.y)
            
            mapping_node = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeMapping" and any(l.to_node == node and l.to_socket.name == "Vector" for l in n.outputs[0].links)), None)
            if not mapping_node:
                mapping_node = tree.nodes.new("ShaderNodeMapping")
                mapping_node.location = (node.location.x - 300, node.location.y)
            
            tree.links.new(texcoord.outputs["UV"], mapping_node.inputs["Vector"])
            tree.links.new(mapping_node.outputs["Vector"], node.inputs["Vector"])
            
            self.report({"INFO"}, "Mapping moved to external")

        else: # INTERNAL
            # 1. Inside group: ensure internal texcoord/mapping are connected
            mapping = ensure_internal_mapping(group_tree)
            texcoord_internal = next((n for n in group_tree.nodes if n.bl_idname == "ShaderNodeTexCoord"), None)
            if texcoord_internal:
                group_tree.links.new(texcoord_internal.outputs["UV"], mapping.inputs["Vector"])
            
            # 2. Outside group: potentially remove or just disconnect
            # We don't want to break other things, so let's just disconnect from this node's Vector input
            for link in node.inputs["Vector"].links:
                tree.links.remove(link)
                
            self.report({"INFO"}, "Mapping moved to internal")

        return {"FINISHED"}


classes = (
    MBS_OT_create_blend_material,
    MBS_OT_load_material_textures,
    MBS_OT_choose_replace_slot,
    MBS_OT_create_blend_mask,
    MBS_OT_hotkey_load_material_textures,
    MBS_OT_hotkey_create_mask,
    MBS_OT_reload_material,
    MBS_OT_open_material_folder,
    MBS_OT_save_preset,
    MBS_OT_preview_material,
    MBS_OT_toggle_mapping,
    MBS_PT_material_blend,
)


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name="Node Editor", space_type="NODE_EDITOR")
    kmi = km.keymap_items.new("mbs.hotkey_load_material_textures", "T", "PRESS", ctrl=True, shift=True)
    keymaps.append((km, kmi))
    kmi = km.keymap_items.new("mbs.hotkey_load_blend_mask", "T", "PRESS", ctrl=True)
    keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps()


def unregister():
    unregister_keymaps()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
