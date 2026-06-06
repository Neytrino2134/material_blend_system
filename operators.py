import os
from pathlib import Path
import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .constants import (
    MATERIAL_A_PATH_PROP,
    MATERIAL_B_PATH_PROP,
    MASK_PATH_PROP,
    GROUP_ROLE_PROP,
    GROUP_NODE_ROLE_PROP,
)
from .helpers import (
    active_material,
    ensure_material,
    selected_mix_group_node,
    material_folder,
    node_input,
    link_if_possible,
    has_group_input,
)
from .nodes import (
    setup_nodes,
    auto_slot,
    load_textures_into_slot,
    create_mask,
    reload_slot,
    find_group_node,
    ensure_internal_mapping,
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
            
            link_if_possible(tree, mix_node.outputs.get("Emission Color"), node_input(bsdf_node, "Emission Color", "Emission"))
            link_if_possible(tree, mix_node.outputs.get("Emission Strength"), node_input(bsdf_node, "Emission Strength"))

            if output_node:
                links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])
            
            self.report({"INFO"}, "Reset to Mix Material")
            return {"FINISHED"}

        node = context.active_node
        if not (node and node.bl_idname == "ShaderNodeGroup"):
            return {"CANCELLED"}

        if not bsdf_node:
            self.report({"ERROR"}, "No Principled BSDF node found.")
            return {"CANCELLED"}
        
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

        link_if_possible(tree, node.outputs.get("Emission Color"), node_input(bsdf_node, "Emission Color", "Emission"))
        link_if_possible(tree, node.outputs.get("Emission Strength"), node_input(bsdf_node, "Emission Strength"))

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
            for link in node.inputs["Vector"].links:
                tree.links.remove(link)
                
            self.report({"INFO"}, "Mapping moved to internal")

        return {"FINISHED"}
