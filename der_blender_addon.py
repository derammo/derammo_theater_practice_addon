import time
import bpy
import subprocess
import threading

def execute_command(self, command):
    self.report({'INFO'}, "$ " + command)
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = result.stdout.strip()
    error = result.stderr.strip()
    print("Executed command:", command)
    if output:
        self.report({'INFO'}, output)
    if error:
        self.report({'ERROR'}, error)

def frame_to_time(frame_number, fps, fps_base):
    # Calculate raw time in seconds
    raw_time = (frame_number - 1) / (fps / fps_base)
    
    # Calculate hours, minutes, seconds, and frames for timecode format
    hours = int(raw_time / 3600)
    minutes = int((raw_time % 3600) / 60)
    seconds = int(raw_time % 60)
    # frames = int(((raw_time % 1) * (fps / fps_base))) # Remaining fractional part as frames
    
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def get_output_dir(self, context):
    scene = context.scene
    output_path = scene.render.filepath
    if not output_path.endswith('/'):
        output_path = '/'.join(output_path.split('/')[:-1]) + '/'
    return output_path

class ModalTimerOperator(bpy.types.Operator):
    """Modal Blender Operator which runs work items on timer events"""
    _timer = None
    _work = []
    _running = False
    _canceled = True
    _flushing = True

    def modal(self, context, event):
        if "MOUSE" not in str(event.type):
            print(f"Tasks: {len(self._work)}, Event Type: {event.type}, Thread ID: {threading.get_ident()}, Blender Thread Info: {bpy.app.background}")

        if event.type in {'RIGHTMOUSE', 'ESC'} and not self._canceled:
            self.report({'ERROR'}, f"{self.bl_label}: abort with {len(self._work)} tasks remaining.")
            # async cancel in case we are running
            self._canceled = True
            print("Cancel requested.")
            return {'PASS_THROUGH'}
        
        if self._running:
            # let it finish
            print("Waiting for running task to finish...")
            return {'PASS_THROUGH'}
        
        if self._canceled:
            print("Cancelling remaining tasks.")
            return self.cancel(context)
        
        if self._flushing:
            # yield to allow report flushing
            self._flushing = False
            print("Flushing reports...")
            return {'PASS_THROUGH'}

        if len(self._work) == 0:
            self.report({'INFO'}, f"{self.bl_label}: completed all tasks.")
            print("All tasks completed.")
            return self.cancel(context)

        if event.type == 'TIMER':
            func = self._work.pop(0)
            self._running = True
            try:
                print(f"Starting task, {len(self._work)} remaining.")
                func(context)
            except Exception as e:
                print(f"Error in task: {str(e)}")
                self.report({'ERROR'}, f"Error in task: {str(e)}")
                self._canceled = True
                return self.cancel(context)
            finally:
                print("Task completed.")
                self._running = False

        return {'PASS_THROUGH'}

    def execute(self, context):
        print("Starting modal timer operator...")
        wm = context.window_manager
        self._running = False
        self._canceled = False
        self._timer = wm.event_timer_add(time_step=0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        return {'FINISHED'}
    
    def flush_reports(self, context):
        print("Requesting report flush...")
        self._flushing = True
        _ = context

    def schedule(self, work_items):
        self._work.extend(work_items)