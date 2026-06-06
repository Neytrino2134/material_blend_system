bl_info = {
    "name": "Material Blend System",
    "author": "Codex",
    "version": (0, 1, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Material Blend",
    "description": "Mix two PBR texture sets through one material mask without Mix Shader.",
    "category": "Material",
}

import bpy

# Handle modular reloading to support Blender's script reload (F3 -> Reload Scripts)
if "constants" in locals():
    import importlib
    importlib.reload(constants)
    importlib.reload(helpers)
    importlib.reload(nodes)
    importlib.reload(operators)
    importlib.reload(ui)
else:
    from . import constants
    from . import helpers
    from . import nodes
    from . import operators
    from . import ui

# Expose core API functions at package level
from .helpers import ensure_material, active_material, node_input, detect_map_type
from .nodes import setup_nodes, find_group_node, load_textures_into_slot, create_mask, reload_slot

classes = (
    operators.MBS_OT_create_blend_material,
    operators.MBS_OT_load_material_textures,
    operators.MBS_OT_choose_replace_slot,
    operators.MBS_OT_create_blend_mask,
    operators.MBS_OT_hotkey_load_material_textures,
    operators.MBS_OT_hotkey_create_mask,
    operators.MBS_OT_reload_material,
    operators.MBS_OT_open_material_folder,
    operators.MBS_OT_save_preset,
    operators.MBS_OT_preview_material,
    operators.MBS_OT_toggle_mapping,
    ui.MBS_PT_material_blend,
)

keymaps = []


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
