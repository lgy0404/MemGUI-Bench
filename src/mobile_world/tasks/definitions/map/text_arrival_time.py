"""Text arrival time task implementation."""

import re

from loguru import logger

from mobile_world.runtime.app_helpers.system import enable_auto_time_sync, reset_maps
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class TextArrivalTimeTask(BaseTask):
    goal = (
        "Search up how long it takes to drive from Orlando to Miami."
        "Text Susan (4538997638) the approximate time I'll be there if I leave at 5 pm."
    )
    correct_phone_number = "4538997638"
    # Drive time ~3.5h, depart 5pm, arrive ~8:30pm. Tolerance: ±15min (8:15pm-8:45pm)
    expected_arrival_time_minutes = 20 * 60 + 30  # 8:30pm in minutes
    tolerance_minutes = 15

    task_tags = {"lang-en"}

    app_names = {"Messages", "Maps"}

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        try:
            reset_maps(controller)
            return True
        except Exception as e:
            logger.error(f"Initialize Google Maps task failed: {e}")
            return False

    def _parse_time_to_minutes(self, time_str: str) -> int | None:
        """Parse time string to minutes from midnight. Supports: 8:30, 8:30pm, 20:30, etc."""
        patterns = [
            r"(\d{1,2}):(\d{2})\s*pm",  # 8:30pm, 8:30 pm
            r"(\d{1,2}):(\d{2})\s*p\.m\.",  # 8:30 p.m.
            r"(\d{1,2}):(\d{2})",  # 8:30 (assume PM)
        ]

        for pattern in patterns:
            match = re.search(pattern, time_str.lower())
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))

                # Convert to 24h format
                if "pm" in time_str.lower() or "p.m." in time_str.lower():
                    if hours != 12:
                        hours += 12
                elif hours < 12:  # Assume PM
                    hours += 12

                return hours * 60 + minutes

        return None

    def _check_time_in_range(self, message_content: str) -> bool:
        """Check if time in message is within tolerance range."""
        time_minutes = self._parse_time_to_minutes(message_content)

        if time_minutes is None:
            logger.info(f"Could not parse time from message: {message_content}")
            return False

        min_time = self.expected_arrival_time_minutes - self.tolerance_minutes
        max_time = self.expected_arrival_time_minutes + self.tolerance_minutes

        parsed_hour = time_minutes // 60
        parsed_min = time_minutes % 60

        logger.info(
            f"Parsed time: {time_minutes} minutes ({parsed_hour}:{parsed_min:02d}), "
            f"Expected range: {min_time}-{max_time} minutes (8:15pm-8:45pm)"
        )

        return min_time <= time_minutes <= max_time

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """Check if the correct SMS was sent to Susan with arrival time in acceptable range."""
        self._check_is_initialized()

        try:
            query_cmd = f"adb -s {controller.device} shell content query --uri content://sms/sent"
            result = execute_adb(query_cmd, output=False, root_required=True)

            if not result.success or not result.output:
                logger.info(
                    f"No SMS found or query failed: {result.error if hasattr(result, 'error') else 'unknown error'}"
                )
                return 0.0

            lines = result.output.strip().split("\n")

            for line in lines:
                if not line.strip():
                    continue

                phone_match = False
                message_content = None

                if (
                    f"address={self.correct_phone_number}" in line
                    or self.correct_phone_number in line
                ):
                    phone_match = True

                if "body=" in line:
                    body_match = re.search(r"body=([^,]+)", line)
                    if body_match:
                        message_content = body_match.group(1).strip()

                if phone_match and message_content:
                    logger.info(
                        f"Checking message to {self.correct_phone_number}: {message_content}"
                    )

                    if self._check_time_in_range(message_content):
                        logger.info(
                            f"Successfully found SMS to {self.correct_phone_number} "
                            f"with arrival time in acceptable range (8:15pm-8:45pm)"
                        )
                        return 1.0

            logger.info(
                f"SMS to {self.correct_phone_number} found but arrival time "
                f"not in acceptable range (8:15pm-8:45pm), or no SMS found"
            )
            return 0.0

        except Exception as e:
            logger.error(f"Error checking message status via ADB: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return 0.0

    def tear_down(self, controller: AndroidController) -> bool:
        """Clean up task - reset Messages app."""
        super().tear_down(controller)
        return True
