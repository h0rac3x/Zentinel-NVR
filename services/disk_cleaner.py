import logging
import sqlite3
from datetime import datetime, timedelta
import os
import shutil
from pathlib import Path
import fcntl
import time
from django.conf import settings

logger = logging.getLogger('zentinel.cleanup')

def main():
    start_time = time.perf_counter()
    logger.info("Starting active recording camera cleanup")
    cameras = get_active_recording_cameras()

    logger.info("Found %s active recording cameras", len(cameras))
    for cam in cameras:
        logger.debug("Processing camera: %s", cam)
        clean_directory(cam)
    elapsed_time = time.perf_counter() - start_time
    logger.info("Cleanup completed in %.4f seconds", elapsed_time)

def get_active_recording_cameras() -> list[dict]:
    """Get all active recording cameras through Django's ORM."""
    from cameras.models import Camera
    
    return list(
        Camera.objects.filter(record_enabled=True, is_active=True)
        .values('id', 'name', 'record_path', 'retention_days')
    )

def clean_directory(cam):
    usage_disk=get_disk_usage_percent(cam['record_path'])
    logger.debug("Disk usage for camera %s: %.2f%%", cam['name'], usage_disk)

    rec_path=cam['record_path']+"/"+cam['name']
    path = Path(rec_path)
    if not path.exists() or not path.is_dir():
        logger.error("Recording path does not exist: %s", rec_path)
        return []
    directories = [entry for entry in path.iterdir() if entry.is_dir()]

    if usage_disk >90.00:
        logger.warning("Storage disk for camera '%s' is more than 90%% full", cam['name'])
        # Emergency cleanup.
        oldest_dir = min(directories, key=lambda d: str(d.name)[-10:])
        # Remove the oldest directory.
        clean_directory_single_pass(oldest_dir)
    
    
    for d in directories:
        strpath=str(d)
        if check_if_old_rec(strpath,cam['retention_days']):
            logger.debug("Removing expired recording directory: %s", strpath)
            clean_directory_single_pass(d)
    return

def check_if_old_rec(strpath, ret_days):
    date_f=strpath[-10:]
    try:
        date = datetime.strptime(date_f, "%Y-%m-%d").date()
    except ValueError:
        logger.warning("'%s': wrong date format, expected YYYY-MM-DD", strpath)
        return False
    today = date.today()
    cutoff_date = today - timedelta(days=ret_days)

    return date < cutoff_date  # True when the directory is older than ret_days.

def get_disk_usage_percent(path: str) -> float:
    """
    Calculate the percentage of disk space used by the specified path.
    
    :param path: Storage path (directory or mount point).
    :return: Used space percentage, or 0.0 when an error occurs.
    """
    if not os.path.exists(path):
        logger.error("Path does not exist: %s", path)
        return 0.0

    try:
        total, used, free = shutil.disk_usage(path)
        used_percent = (used / total) * 100
        return round(used_percent, 2)
    except Exception as e:
        logger.error("Unable to read disk space for %s", path, exc_info=True)
        return 0.0

def is_file_open_or_locked(file_path: Path, min_age_seconds: float = 3.0) -> bool:
    """O(1) check: returns True if file is actively being written by FFmpeg or locked."""
    try:
        # Check stat info from inode (size and mtime)
        stat = file_path.stat()
        now = time.time()

        # If modified in the last N seconds or empty (just created), it's active
        if (now - stat.st_mtime) < min_age_seconds or stat.st_size == 0:
            return True

        # Fallback OS low-level write access check
        fd = os.open(file_path, os.O_RDWR)
        os.close(fd)
        return False
    except (OSError, IOError):
        # File is locked, unreadable, or missing
        return True

def clean_directory_single_pass(dir_path: Path | str) -> bool:
    """Deletes closed files in a single pass and removes the dir if fully emptied."""
    directory = Path(dir_path)

    if not directory.exists() or not directory.is_dir():
        return False

    has_active_files = False

    for item in directory.iterdir():
        if item.is_file():
            # Skip file if locked or open
            if is_file_open_or_locked(item):
                logger.debug("File in use: %s", item.name)
                has_active_files = True
                continue

            # Delete closed file
            try:
                os.remove(item)
                logger.info("File removed: %s", item.name)
            except OSError as e:
                logger.error("Failed to remove %s", item.name, exc_info=True)
                has_active_files = True

        elif item.is_dir():
            has_active_files = True

    # Remove directory if no active or remaining files
    if not has_active_files:
        try:
            directory.rmdir()
            logger.info("Empty directory removed: %s", directory.name)
            return True
        except OSError as e:
            logger.error("Failed to remove directory %s", directory.name, exc_info=True)
            return False
    else:
        logger.debug("Directory retained: %s", directory.name)
        return False

if __name__ == "__main__":
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    main()