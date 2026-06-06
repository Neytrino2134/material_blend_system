import os
import re
from pathlib import Path
import bpy
from .constants import (
    MAP_TAGS,
    DEFAULT_MATERIAL_NAME,
    MATERIAL_A_PATH_PROP,
    MATERIAL_B_PATH_PROP,
    GROUP_NODE_ROLE_PROP,
    MIX_GROUP_NAME,
)


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


def material_folder(mat, slot):
    prop = MATERIAL_A_PATH_PROP if slot == "A" else MATERIAL_B_PATH_PROP
    value = mat.get(prop, "")
    return value if value and os.path.isdir(value) else ""
