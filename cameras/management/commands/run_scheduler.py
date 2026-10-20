import time
import logging
from django.core.management.base import BaseCommand
from apscheduler.schedulers.background import BackgroundScheduler
from services.disk_cleaner import main as run_disk_cleaner

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Start the background job scheduler (disk cleaner)"

    def handle(self, *args, **options):
        scheduler = BackgroundScheduler()

        # Run the cleanup job hourly.
        scheduler.add_job(
            run_disk_cleaner,
            'interval',
            hours=1,
            id='disk_cleaner_job',
            replace_existing=True
        )

        scheduler.start()
        self.stdout.write(self.style.SUCCESS("[SCHEDULER] APScheduler started successfully."))

        try:
            while True:
                time.sleep(2)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
            self.stdout.write(self.style.NOTICE("[SCHEDULER] Scheduler stopped."))