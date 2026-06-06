import bpy
from bpy.types import Panel
from .constants import (
    GROUP_ROLE_PROP,
    MATERIAL_A_PATH_PROP,
    MATERIAL_B_PATH_PROP,
)
from .helpers import active_material


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
