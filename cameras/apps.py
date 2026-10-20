import os
import sys
import logging
from django.apps import AppConfig

logger = logging.getLogger('zentinel')

class CamerasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cameras'

    def ready(self):
        # Skip startup work during migrations and other CLI commands.
        if any(cmd in sys.argv for cmd in ['makemigrations', 'migrate', 'collectstatic', 'shell']):
            return

        # Avoid duplicate startup work in the runserver parent process.
        if 'runserver' in sys.argv and not os.environ.get('RUN_MAIN'):
            return

        # Import models and services here to avoid circular imports.
        try:
            from .models import Camera
            from services.recorder import start_camera_recording
            from services.go2rtc import sync_camera_to_go2rtc

            logger.info("Restoring active camera state and recordings")
            active_cameras = Camera.objects.filter(is_active=True)

            for cam in active_cameras:
                # Sync the stream with go2rtc.
                sync_camera_to_go2rtc(cam)

                # Start recording when it is enabled.
                if cam.record_enabled:
                    start_camera_recording(cam)

        except Exception as e:
            logger.error("Failed to restore recordings", exc_info=True)