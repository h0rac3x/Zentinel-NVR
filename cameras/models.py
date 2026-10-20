import logging

from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger('zentinel')

class Camera(models.Model):
    PROTOCOL_CHOICES = [
        ('ONVIF', 'ONVIF'),
        ('RTSP', 'RTSP'),
        ('HTTP', 'HTTP'),
    ]

    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default='ONVIF')
    port = models.IntegerField(default=8899)
    username = models.CharField(max_length=50, default='admin', blank=True)
    password = models.CharField(max_length=50, blank=True)
    
    custom_main_url = models.CharField(max_length=255, blank=True, null=True)
    custom_sub_url = models.CharField(max_length=255, blank=True, null=True)

    is_active = models.BooleanField(default=True, verbose_name=_("Camera active"))
    record_enabled = models.BooleanField(default=False, verbose_name=_("Recording enabled"))
    retention_days = models.IntegerField(default=7, verbose_name=_("Retention days"))
    record_path = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name=_("Recording directory"),
        help_text=_("Leave blank to use the default path")
    )
    segment_duration_minutes = models.IntegerField(
        default=15, 
        verbose_name=_("Segment duration (minutes)")
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.ip_address})"

    @property
    def stream_main_name(self):
        return f"cam_{self.id}_main"

    @property
    def stream_sub_name(self):
        return f"cam_{self.id}_sub"

    def get_effective_record_path(self):
        """Return the camera's base recording directory."""
        if self.record_path and self.record_path.strip():
            return self.record_path.strip()
        base_dir = getattr(settings, 'RECORDINGS_DIR', '/home/recordings_zentinel')
        return f"{base_dir}/camera_{self.id}"

    def get_source_urls(self):
        auth = f"{self.username}:{self.password}@" if self.username else ""
        
        if self.custom_main_url:
            main_url = self.custom_main_url
        elif self.protocol == 'HTTP':
            main_url = f"http://{auth}{self.ip_address}:{self.port}"
        elif self.protocol == 'ONVIF':
            main_url = f"onvif://{auth}{self.ip_address}:{self.port}?subtype=000"  
        else:
            main_url = f"rtsp://{auth}{self.ip_address}:{self.port}/h264/ch1/main/av_stream"

        if self.custom_sub_url:
            sub_url = self.custom_sub_url
        elif self.protocol == 'HTTP':
            sub_url = self.custom_sub_url or main_url
        elif self.protocol == 'ONVIF':
            sub_url = f"onvif://{auth}{self.ip_address}:{self.port}?subtype=001"                
        else:
            sub_url = f"rtsp://{auth}{self.ip_address}:{self.port}/h264/ch1/sub/av_stream"
            
        logger.debug("Resolved main stream URL: %s", main_url)
        logger.debug("Resolved sub stream URL: %s", sub_url)
        return main_url, sub_url
