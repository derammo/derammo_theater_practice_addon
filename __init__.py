import bpy
import re
from .der_blender_addon import execute_command, frame_to_time, get_output_dir, ModalTimerOperator

class WriteTimestampsOperator(bpy.types.Operator):
    bl_idname = "derammo.write_timestamps"
    bl_label = "Write Timestamps for Youtube"
    bl_description = "Write markers.txt with timeline markers in timecode format for YouTube Description"
    
    def execute(self, context):
        output_dir = get_output_dir(self, context)
        scene = context.scene
        fps = scene.render.fps
        fps_base = scene.render.fps_base
        markers = scene.timeline_markers
        sorted_markers = sorted(markers, key=lambda marker: marker.frame)

        marker_path = output_dir + 'markers.txt' 
        with open(marker_path, 'w') as mf:
            for marker in sorted_markers:
                message = '{} {}\n'.format(frame_to_time(marker.frame, fps, fps_base), marker.name)
                self.report({'INFO'}, message.strip())
                mf.write(message)
        return {'FINISHED'}

class RenderAudioFilesOperator(ModalTimerOperator):
    bl_idname = "derammo.render_audio_files"
    bl_label = "Render Audio Files"
    bl_description = "Render audio files between timeline markers in the VSE"

    track = 1
    previous = None
    markers = []    

    def work(self, context):
        if self.previous is None:
            self.report({'ERROR'}, "Priming previous marker, that should have been set already.")
            self.previous = self.markers.pop(0)
            return
            
        next = self.markers.pop(0)
        output_dir = get_output_dir(self, context)
        scene = context.scene

        # save rendering settings
        o_frame_start = scene.frame_start
        o_frame_end = scene.frame_end
        o_codec = scene.render.ffmpeg.codec
        o_render_filepath = scene.render.filepath
        
        try:
            # Configure render settings for audio only
            scene.render.image_settings.file_format = 'FFMPEG'
            scene.render.ffmpeg.format = 'MPEG4'  
            scene.render.ffmpeg.audio_codec = 'AAC'
            scene.render.ffmpeg.codec =  'NONE'

            output_filename = re.sub(r"[^a-zA-Z0-9]", "_", self.previous.name) + ".aac"
            scene.frame_start = self.previous.frame
            scene.frame_end = next.frame

            # Set the output file path
            scene.render.filepath = output_dir + 'audio/' + output_filename

            # Ensure sequencer is enabled for audio rendering
            scene.sequence_editor_create() # Create a sequence editor if one doesn't exist
            scene.render.use_sequencer = True

            # Perform the audio mixdown, blocking
            self.report({'INFO'}, "rendering " + scene.render.filepath)
            bpy.ops.sound.mixdown(filepath=scene.render.filepath, check_existing=True, container='AAC', codec='AAC')
            
            # encapsulate as M4A            
            encapsulate = '/opt/homebrew/bin/ffmpeg -y -i ' + scene.render.filepath + ' '
            
            # suppress non-error output that ends up in stderr
            encapsulate += '-loglevel error -hide_banner -nostats '

            # album art on all tracks
            encapsulate += '-i ' + output_dir + 'album.png ' \
                        + '-map 0:0 -map 1:0 '

            encapsulate += '-codec copy ' \
                + '-id3v2_version 3 ' \
                + '-metadata title="' + self.previous.name + '" ' \
                + '-metadata album="' + scene.name + '" ' \
                + '-metadata track="' + str(self.track) + '" ' \
                + '-metadata artist="derammo" ' \
                + '-metadata genre="Musicals" '
                
            # album art on all tracks
            encapsulate += '-disposition:v attached_pic -metadata:s:v title="Album cover" -metadata:s:v comment="Cover (front)" '
            
            encapsulate += re.sub(r".aac$", ".m4a", scene.render.filepath)

            # render m4a
            execute_command(self, encapsulate)
                
            # remove AAC
            execute_command(self, '/usr/bin/trash ' + scene.render.filepath)
            
            self.previous = next    
            self.track += 1
        finally:    
            # restore render settings
            scene.frame_start = o_frame_start
            scene.frame_end = o_frame_end
            scene.render.filepath = o_render_filepath
            scene.render.ffmpeg.codec = o_codec

            self.flush_reports(context)

    def execute(self, context):
        self.track = 1
        self.markers = sorted(context.scene.timeline_markers, key=lambda marker: marker.frame)
        self.previous = self.markers.pop(0) if self.markers else None
        self.schedule([self.work] * len(self.markers))

        return super().execute(context)
    
class FillGapsOperator(bpy.types.Operator):
    bl_idname = "derammo.fill_gaps"
    bl_label = "Fill Channel Gaps"
    bl_description = "Fill gaps in channel currently selected strip in the VSE and adjust markers accordingly"
    
    def execute(self, context):
        selected_strips = context.selected_sequences
        if not selected_strips:
            self.report({'ERROR'}, "No strips selected.")
            return {'CANCELLED'}
        
        channels_with_selected_strips = set(strip.channel for strip in selected_strips)
        if len(channels_with_selected_strips) > 1:
            self.report({'ERROR'}, "More than one channel found. Please select strips from only one channel.")
            return {'CANCELLED'}

        channel = channels_with_selected_strips.pop()
        self.report({'INFO'}, f"Channel {channel}:")
        found = (strip for strip in context.scene.sequence_editor.sequences if strip.channel == channel)
        strips_in_channel = sorted(found, key=lambda s: s.frame_final_start)
        previous = strips_in_channel.pop(0) if strips_in_channel else None
        gaps_fixed = 0
        markers_adjusted = 0
        for strip in strips_in_channel:
            self.report({'DEBUG'}, f"  - {strip.name} (Start: {strip.frame_final_start}, End: {strip.frame_final_end})")
            gap = strip.frame_final_start - previous.frame_final_end
            if gap <= 0:
                previous = strip
                continue
            self.report({'INFO'}, f"    Filling gap of {gap} frames before {strip.name}")
            text_strip = context.scene.sequence_editor.sequences.new_effect(
                name=f"GapFiller_{previous.frame_final_end}_{strip.frame_final_start}",
                type='TEXT',
                channel=channel,
                frame_start=previous.frame_final_end,
                frame_end=strip.frame_final_start
            )
            gaps_fixed += 1
            text_strip.text = "Gap Filler"
            for marker in context.scene.timeline_markers:
                if previous.frame_final_end <= marker.frame:
                    marker.frame += gap
                    markers_adjusted += 1
            previous = strip
        self.report({'INFO'}, f"Gaps fixed: {gaps_fixed}, Markers adjusted: {markers_adjusted}")
        return {'FINISHED'}

    
class PrintStripsOperator(bpy.types.Operator):
    bl_idname = "derammo.print_strips"
    bl_label = "Print Channel Strips"
    bl_description = "Print strips in any channels with currently selected strips in the VSE"

    def execute(self, context):
        selected_strips = context.selected_sequences
        channels_with_selected_strips = set(strip.channel for strip in selected_strips)
        
        for channel in sorted(channels_with_selected_strips):
            self.report({'INFO'}, f"Channel {channel}:")
            found = (strip for strip in context.scene.sequence_editor.sequences if strip.channel == channel)
            strips_in_channel = sorted(found, key=lambda s: s.frame_final_start)
            for strip in strips_in_channel:
                self.report({'INFO'}, f"  - {strip.name} (Start: {strip.frame_final_start}, End: {strip.frame_final_end})")

        if not selected_strips:
            self.report({'ERROR'}, "No strips selected.")
            return {'CANCELLED'}

        return {'FINISHED'}

def strip_menu_extension(self, context):
    self.layout.separator()
    self.layout.operator(PrintStripsOperator.bl_idname, text=PrintStripsOperator.bl_label)
    self.layout.operator(FillGapsOperator.bl_idname, text=FillGapsOperator.bl_label)

def render_menu_extension(self, context):
    self.layout.separator()
    self.layout.operator(WriteTimestampsOperator.bl_idname, text=WriteTimestampsOperator.bl_label)
    self.layout.operator(RenderAudioFilesOperator.bl_idname, text=RenderAudioFilesOperator.bl_label)

classes = [
    PrintStripsOperator,
    FillGapsOperator,
    WriteTimestampsOperator,
    RenderAudioFilesOperator,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.SEQUENCER_MT_strip.append(strip_menu_extension)
    bpy.types.TOPBAR_MT_render.append(render_menu_extension)
    print("registered")

def unregister():
    bpy.types.TOPBAR_MT_render.remove(render_menu_extension)
    bpy.types.SEQUENCER_MT_strip.remove(strip_menu_extension)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

def unregister():
    bpy.types.TOPBAR_MT_render.remove(render_menu_extension)
    bpy.types.SEQUENCER_MT_strip.remove(strip_menu_extension)
    bpy.utils.unregister_class(RenderAudioFilesOperator)
    bpy.utils.unregister_class(WriteTimestampsOperator)
    bpy.utils.unregister_class(FillGapsOperator)
    bpy.utils.unregister_class(PrintStripsOperator)
