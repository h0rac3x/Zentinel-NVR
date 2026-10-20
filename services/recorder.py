import logging
import os
import re
import time
import threading
import subprocess
from datetime import datetime

logger = logging.getLogger('zentinel')

ACTIVE_RECORDERS = {}
HEALTH_CHECK_THREAD = None
HEALTH_CHECK_RUNNING = False

def sanitize_folder_name(name):
    """Remove special characters from a camera name."""
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')

def log_ffmpeg_output(pipe, camera_name):
    """Read FFmpeg stderr line by line and send it to the logger."""
    for line in iter(pipe.readline, b''):
        line_str = line.decode('utf-8', errors='ignore').strip()
        if line_str:
            logger.error("FFmpeg [%s]: %s", camera_name, line_str)
    pipe.close()

def start_camera_recording(camera):
    """Start the FFmpeg recording process."""
    stop_camera_recording(camera.id)

    if not camera.record_enabled:
        return

    # Small delay to avoid race conditions when the stream starts
    time.sleep(2)

    input_rtsp = f"rtsp://127.0.0.1:8554/{camera.stream_main_name}"
    base_dir = camera.get_effective_record_path()
    clean_cam_name = sanitize_folder_name(camera.name)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = os.path.join(base_dir, clean_cam_name, today_str)
    os.makedirs(output_dir, exist_ok=True)

    output_pattern = os.path.join(output_dir, "%H-%M-%S.mp4")
    segment_seconds = max(60, camera.segment_duration_minutes * 60)

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-fflags", "nobuffer",
        "-i", input_rtsp,
        "-c:v", "copy",
        "-c:a", "aac",
        "-filter:a", "volume=3.0",
        "-b:a", "128k",
        "-f", "segment",
        "-segment_time", str(segment_seconds),
        "-segment_atclocktime", "1",
        "-reset_timestamps", "1",
        "-strftime", "1",
        "-segment_format_options", "movflags=+empty_moov+default_base_moof+frag_keyframe",
        output_pattern
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        # Start daemon thread to capture and log FFmpeg stderr in real time
        threading.Thread(
            target=log_ffmpeg_output, 
            args=(proc.stderr, camera.name), 
            daemon=True
        ).start()

        ACTIVE_RECORDERS[camera.id] = {
            'process': proc,
            'camera': camera
        }
        logger.info("Recording started for '%s' at %s", camera.name, output_dir)
        
        ensure_health_check_running()
    except Exception as e:
        logger.error("Failed to start recording for camera %s", camera.id, exc_info=True)

def stop_camera_recording(camera_id):
    """Stop the recording process."""
    if camera_id in ACTIVE_RECORDERS:
        data = ACTIVE_RECORDERS.pop(camera_id)
        proc = data['process']
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        logger.info("Recording stopped for camera %s", camera_id)

def check_recorders_health():
    """Background worker that restarts stopped FFmpeg processes."""
    global HEALTH_CHECK_RUNNING
    while HEALTH_CHECK_RUNNING:
        time.sleep(10)  # Check every 10 seconds.
        
        dead_cameras = []
        for camera_id, data in list(ACTIVE_RECORDERS.items()):
            proc = data['process']
            cam = data['camera']
            
            if proc.poll() is not None:
                logger.warning("Recording process stopped for camera '%s' (ID: %s); restarting", cam.name, camera_id)
                dead_cameras.append(cam)
        
        for cam in dead_cameras:
            start_camera_recording(cam)

def ensure_health_check_running():
    """Start the background monitoring thread when it is stopped."""
    global HEALTH_CHECK_THREAD, HEALTH_CHECK_RUNNING
    if not HEALTH_CHECK_RUNNING:
        HEALTH_CHECK_RUNNING = True
        HEALTH_CHECK_THREAD = threading.Thread(target=check_recorders_health, daemon=True)
        HEALTH_CHECK_THREAD.start()
        logger.info("Recording auto-recovery thread started")
