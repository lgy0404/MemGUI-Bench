import csv
import json
import os
import random
import re
import subprocess
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from queue import Queue

from dotenv import load_dotenv
from joblib import Parallel, delayed
from loguru import logger

from mobile_world.agents.base import (
    BaseAgent,
    MCPAgent,
    TransientLLMError,
    configure_llm_rate_limits,
    get_llm_rate_limit_stats,
)
from mobile_world.agents.registry import create_agent
from mobile_world.runtime.client import (
    AndroidEnvClient,
    AndroidMCPEnvClient,
    scan_finished_tasks,
)
from mobile_world.runtime.utils.docker import (
    discover_backends,
)
from mobile_world.runtime.utils.models import (
    ANSWER,
    DEFAULT_IMAGE,
    DEFAULT_NAME_PREFIX,
    ENV_FAIL,
    FINISHED,
    UNKNOWN,
)
from mobile_world.runtime.utils.trajectory_logger import (
    SCORE_FILE_NAME,
    TrajLogger,
    ensure_log_root_writable,
)

load_dotenv()

MEMGUI_MAX_STEP_MULTIPLIER = 2.5
MEMGUI_DEFAULT_MAX_STEP_FALLBACK = 15
MEMGUI_SUCCESS_THRESHOLD = 0.99
MEMGUI_EVAL_ERROR_MARKER = "MemGUI-Eval error"
MEMGUI_ATTEMPT_EVAL_RE = re.compile(r"^.+_attempt_(?P<attempt>\d+)_evaluation$")
DEVICE_RECOVERY_WAIT_SECONDS = 240
DEVICE_RECOVERY_POLL_SECONDS = 10
BACKEND_EMULATOR_RESTART_ATTEMPTS = int(
    os.getenv("MEMGUI_BACKEND_EMULATOR_RESTART_ATTEMPTS", "2")
)
BACKEND_EMULATOR_RESTART_TIMEOUT_SECONDS = int(
    os.getenv("MEMGUI_BACKEND_EMULATOR_RESTART_TIMEOUT_SECONDS", "900")
)
BACKEND_REBUILD_TIMEOUT_SECONDS = int(
    os.getenv("MEMGUI_BACKEND_REBUILD_TIMEOUT_SECONDS", "1200")
)
AUTO_REBUILD_UNHEALTHY_BACKEND = os.getenv(
    "MEMGUI_AUTO_REBUILD_UNHEALTHY_BACKEND", "true"
).lower() not in {"0", "false", "no", "off"}
MEMGUI_LLM_INFRA_RETRIES = int(os.getenv("MEMGUI_LLM_INFRA_RETRIES", "3"))
_METADATA_UPDATE_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _get_memgui_task_max_steps() -> dict[str, int]:
    """Load MemGUI's original per-task step budgets from the benchmark CSV."""
    from mobile_world.tasks.memgui_registry import MemGUITaskRegistry

    task_max_steps: dict[str, int] = {}
    registry = MemGUITaskRegistry()
    for task_name, task in registry.tasks.items():
        try:
            golden_steps = float(task.record.golden_steps)
        except ValueError:
            task_max_steps[task_name] = MEMGUI_DEFAULT_MAX_STEP_FALLBACK
        else:
            task_max_steps[task_name] = max(1, int(golden_steps * MEMGUI_MAX_STEP_MULTIPLIER + 1))
    return task_max_steps


def _resolve_task_max_step(
    suite_family: str,
    task_name: str,
    requested_max_step: int | None,
) -> int:
    """Resolve the effective max step for a task.

    A positive CLI value always wins. For MemGUI-Bench, omitting the value keeps
    the original benchmark behavior: golden_steps * 2.5 + 1. Negative values
    keep the MobileWorld convention of unlimited steps.
    """
    if requested_max_step is not None:
        return requested_max_step

    if suite_family == "memgui_bench":
        max_steps = _get_memgui_task_max_steps()
        return max_steps.get(task_name, MEMGUI_DEFAULT_MAX_STEP_FALLBACK)

    return -1


def _create_attempt_traj_logger(
    log_file_root: str,
    task_name: str,
    attempt_num: int,
    pass_at_k: int,
) -> TrajLogger:
    """Create a trajectory logger for one pass@k attempt."""
    if pass_at_k <= 1 or attempt_num == 1:
        return TrajLogger(log_file_root, task_name)

    attempt_root = os.path.join(log_file_root, "_attempt_trajs", task_name)
    return TrajLogger(attempt_root, f"attempt_{attempt_num}")


def _is_successful_score(score: float | int | str | None) -> bool:
    if score is None:
        return False
    try:
        return float(score) > MEMGUI_SUCCESS_THRESHOLD
    except (TypeError, ValueError):
        return False


def _parse_score_file(result_file: str) -> tuple[float | None, str]:
    with open(result_file) as f:
        lines = f.readlines()

    score = None
    if lines and "score:" in lines[0]:
        try:
            score = float(lines[0].split("score:", 1)[1].strip())
        except ValueError:
            score = None
    reason = lines[1].strip() if len(lines) > 1 else ""
    return score, reason


def _has_memgui_csv_evaluation(
    log_file_root: str,
    task_name: str,
    max_attempt: int | None = None,
) -> bool:
    csv_path = os.path.join(log_file_root, "_memgui_eval", "results.csv")
    if not os.path.exists(csv_path):
        return False

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            row = next(
                (item for item in reader if item.get("task_identifier") == task_name),
                None,
            )
    except (OSError, csv.Error) as e:
        logger.warning(f"Error reading MemGUI results.csv in {log_file_root}: {e}")
        return False

    if not row:
        return False

    for field in fieldnames:
        match = MEMGUI_ATTEMPT_EVAL_RE.match(field)
        if not match:
            continue
        if max_attempt is not None and int(match.group("attempt")) > max_attempt:
            continue
        value = str(row.get(field, "")).strip().upper()
        if value in {"S", "F", "E"}:
            return True
    return False


def _scan_finished_memgui_pass_at_k_tasks(
    log_file_root: str,
    task_list: list[str],
    pass_at_k: int,
) -> tuple[list[str], list[float]]:
    """Find MemGUI tasks that should be skipped in the current log root.

    This mirrors the original MemGUI-Bench behavior more closely than the
    plain MobileWorld `result.txt` scan: a previous success can stop all later
    attempts, and a completed aggregate pass@K run should be skipped. A lone
    failed pass@1 result should not block a later pass@3 run from adding more
    attempts. A MemGUI-Eval infrastructure error without a CSV decision should
    not be treated as finished, because reruns should retry evaluation after the
    environment is fixed.
    """
    finished_tasks: list[str] = []
    finished_scores: list[float] = []
    pass_marker = f"pass@{pass_at_k}:"

    for task_name in task_list:
        result_file = os.path.join(log_file_root, task_name, SCORE_FILE_NAME)
        if not os.path.exists(result_file):
            continue
        try:
            score, reason = _parse_score_file(result_file)
        except OSError as e:
            logger.warning(f"Error reading result.txt for {task_name}: {e}")
            continue

        if score is None:
            continue
        if (
            MEMGUI_EVAL_ERROR_MARKER in reason
            and not _has_memgui_csv_evaluation(log_file_root, task_name, pass_at_k)
        ):
            continue
        if pass_at_k <= 1:
            finished_tasks.append(task_name)
            finished_scores.append(score)
            continue
        if _is_successful_score(score) or pass_marker in reason:
            finished_tasks.append(task_name)
            finished_scores.append(score)

    return finished_tasks, finished_scores


def _update_log_metadata(metadata_path: str, updates: dict) -> None:
    """Merge run metadata without changing the existing suite-family guard."""
    with _METADATA_UPDATE_LOCK:
        metadata = {}
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read existing metadata at {metadata_path}: {e}")

        metadata.update(updates)
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)


def _infra_failure_dir(log_file_root: str, task_name: str) -> str:
    return os.path.join(log_file_root, "_infra_failures", task_name)


def _write_infra_failure(
    *,
    log_file_root: str,
    task_name: str,
    attempt_num: int,
    failure_type: str,
    reason: str,
    infra_retries: int,
    env_url: str | None = None,
    container_name: str | None = None,
) -> str:
    """Record a terminal infra failure without converting it into score=0."""
    task_dir = os.path.join(log_file_root, task_name)
    os.makedirs(task_dir, exist_ok=True)
    traj_path = os.path.join(task_dir, "traj.json")
    if not os.path.exists(traj_path):
        with open(traj_path, "w") as f:
            json.dump({}, f)

    failure_dir = _infra_failure_dir(log_file_root, task_name)
    os.makedirs(failure_dir, exist_ok=True)
    failure_path = os.path.join(failure_dir, f"attempt_{attempt_num}.json")
    payload = {
        "task_name": task_name,
        "attempt": attempt_num,
        "failure_type": failure_type,
        "reason": reason,
        "infra_retries": infra_retries,
        "env_url": env_url,
        "container_name": container_name,
        "timestamp": datetime.now().isoformat(),
    }
    with open(failure_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return failure_path


def _append_infra_failure_metadata(metadata_path: str, task_name: str, failure_type: str) -> None:
    with _METADATA_UPDATE_LOCK:
        metadata = {}
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read existing metadata at {metadata_path}: {e}")
        tasks = metadata.get("infra_failed_tasks")
        if not isinstance(tasks, list):
            tasks = []
        if task_name not in tasks:
            tasks.append(task_name)
        counts = metadata.get("infra_failure_counts")
        if not isinstance(counts, dict):
            counts = {}
        counts[failure_type] = int(counts.get(failure_type, 0)) + 1
        metadata.update(
            {
                "infra_failed_tasks": tasks,
                "infra_failure_counts": counts,
                "updated_at": datetime.now().isoformat(),
            }
        )
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)


def _increment_metadata_counter(metadata_path: str, key: str, amount: int = 1) -> None:
    with _METADATA_UPDATE_LOCK:
        metadata = {}
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read existing metadata at {metadata_path}: {e}")
        metadata[key] = int(metadata.get(key, 0) or 0) + amount
        metadata["updated_at"] = datetime.now().isoformat()
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)


def _is_transient_infra_error(exc: Exception) -> bool:
    return isinstance(exc, TransientLLMError) or _is_device_unhealthy_error(exc)


def _write_pass_at_k_result(
    log_file_root: str,
    task_name: str,
    pass_at_k: int,
    attempt_results: list[dict],
) -> tuple[float, str]:
    """Write the aggregate pass@k result to the canonical task folder."""
    best_score = max((float(result["score"]) for result in attempt_results), default=0.0)
    successful_attempts = [
        int(result["attempt"]) for result in attempt_results if float(result["score"]) > 0.99
    ]
    best_attempt = successful_attempts[0] if successful_attempts else None
    latest_reason = attempt_results[-1].get("reason", "") if attempt_results else ""

    if best_attempt is not None:
        reason = (
            f"pass@{pass_at_k}: success at attempt {best_attempt}; "
            f"successful_attempts={successful_attempts}; "
            f"attempts_run={len(attempt_results)}/{pass_at_k}"
        )
    else:
        reason = f"pass@{pass_at_k}: all {len(attempt_results)} attempts failed"
    if latest_reason:
        reason = f"{reason}; latest_reason={latest_reason}"

    task_dir = os.path.join(log_file_root, task_name)
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, SCORE_FILE_NAME), "w") as f:
        f.write(f"score: {best_score}\nreason: {reason}")

    return best_score, reason


def _write_failure_result(
    log_file_root: str, task_name: str, reason: str
) -> tuple[float, str]:
    """Write a terminal failed result so aborted tasks do not look perpetually running."""
    task_dir = os.path.join(log_file_root, task_name)
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, SCORE_FILE_NAME), "w") as f:
        f.write(f"score: 0.0\nreason: {reason}")
    return 0.0, reason


def _safe_tear_down_task(
    env: AndroidEnvClient, agent: BaseAgent | None, task_name: str
) -> None:
    """Best-effort cleanup after an attempt fails before normal teardown."""
    try:
        res = env.tear_down_task(task_type=task_name)
        logger.debug(f"tear_down_task response after failure: {res}")
    except Exception as e:
        logger.warning(f"Error tearing down failed task {task_name}: {e}")

    if agent is not None:
        try:
            agent.done()
        except Exception as e:
            logger.warning(f"Error finalizing agent after failed task {task_name}: {e}")


def _wait_for_env_recovery(
    env: AndroidEnvClient,
    timeout: int = DEVICE_RECOVERY_WAIT_SECONDS,
    poll_interval: int = DEVICE_RECOVERY_POLL_SECONDS,
) -> bool:
    """Wait for an unhealthy environment to report healthy again."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if env.health():
            env._initialized = False
            return True
        time.sleep(poll_interval)
    return False


def _is_device_unhealthy_error(error: BaseException) -> bool:
    return "Device is not healthy" in str(error)


def _env_map_from_container(container_info: dict) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for item in container_info.get("Config", {}).get("Env", []) or []:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        env_map[key] = value
    return env_map


def _host_port_from_container(container_info: dict, container_port: int) -> int | None:
    bindings = (
        container_info.get("NetworkSettings", {})
        .get("Ports", {})
        .get(f"{container_port}/tcp")
    )
    if not bindings:
        return None
    try:
        return int(bindings[0].get("HostPort"))
    except (TypeError, ValueError, IndexError):
        return None


def _mounted_source(container_info: dict, destination: str) -> Path | None:
    for mount in container_info.get("Mounts", []) or []:
        if mount.get("Destination") != destination:
            continue
        source = mount.get("Source")
        if source:
            return Path(source)
    return None


def _restart_emulator_in_container(
    container_name: str,
    timeout: int = BACKEND_EMULATOR_RESTART_TIMEOUT_SECONDS,
) -> bool:
    """Force restart the emulator inside an existing runtime container."""
    if not container_name:
        return False

    command = f"""
set -euo pipefail
pkill -f '[s]tart_memgui_emulator.sh' 2>/dev/null || true
pkill -f '[s]tart_emulator.sh' 2>/dev/null || true
pkill -f '[a]uthorize_adb_grpc.py' 2>/dev/null || true
adb devices | awk '/emulator/ {{print $1}}' | xargs -r -I {{}} adb -s "{{}}" emu kill || true
adb kill-server >/dev/null 2>&1 || true
sleep 2
if [ -x /app/docker/start_memgui_emulator.sh ]; then
  script=/app/docker/start_memgui_emulator.sh
elif [ -x /app/docker/start_emulator.sh ]; then
  script=/app/docker/start_emulator.sh
else
  echo "No emulator startup script found in /app/docker" >&2
  exit 127
fi
echo "Manual backend recovery: restarting emulator via $script" >> /var/log/emulator.log
EMULATOR_TIMEOUT={timeout} MEMGUI_EMULATOR_START_ATTEMPTS=2 bash "$script" >> /var/log/emulator.log 2>&1
"""
    try:
        result = subprocess.run(
            ["docker", "exec", container_name, "/bin/bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout + 60,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "Timed out while restarting emulator inside container {} after {}s",
            container_name,
            timeout,
        )
        return False

    if result.returncode != 0:
        logger.warning(
            "Failed to restart emulator inside container {}: {}{}",
            container_name,
            result.stderr,
            result.stdout,
        )
        return False

    return True


def _rebuild_backend_container(
    container_name: str,
    env_image: str = DEFAULT_IMAGE,
) -> bool:
    """Remove and recreate a backend container with the same name and ports."""
    if not container_name:
        return False

    from mobile_world.core.api.env import launch_container, remove_container
    from mobile_world.runtime.utils.docker import docker_inspect
    from mobile_world.runtime.utils.models import (
        DEFAULT_CONTAINER_ENTRYPOINT,
        DEFAULT_EMULATOR_TIMEOUT,
        ContainerConfig,
    )

    container_info = docker_inspect(container_name)
    if not container_info:
        logger.warning("Cannot rebuild container {}; docker inspect returned nothing", container_name)
        return False

    backend_port = _host_port_from_container(container_info, 6800)
    viewer_port = _host_port_from_container(container_info, 7860)
    adb_port = _host_port_from_container(container_info, 5556)
    if backend_port is None or viewer_port is None or adb_port is None:
        logger.warning(
            "Cannot rebuild container {}; failed to recover host ports from inspect data",
            container_name,
        )
        return False

    env_map = _env_map_from_container(container_info)
    try:
        emulator_timeout = int(env_map.get("EMULATOR_TIMEOUT", DEFAULT_EMULATOR_TIMEOUT))
    except ValueError:
        emulator_timeout = DEFAULT_EMULATOR_TIMEOUT
    env_file_path = _mounted_source(container_info, "/app/service/.env")
    dev_src_path = _mounted_source(container_info, "/app/service/src")
    entrypoint = container_info.get("Config", {}).get("Entrypoint")
    if isinstance(entrypoint, list):
        entrypoint = entrypoint[0] if len(entrypoint) == 1 else DEFAULT_CONTAINER_ENTRYPOINT
    elif not isinstance(entrypoint, str):
        entrypoint = DEFAULT_CONTAINER_ENTRYPOINT

    config = ContainerConfig(
        name=container_name,
        backend_port=backend_port,
        viewer_port=viewer_port,
        adb_port=adb_port,
        image=env_image or container_info.get("Config", {}).get("Image") or DEFAULT_IMAGE,
        dev_mode=env_map.get("DEV_MODE", "").lower() in {"1", "true", "yes"},
        enable_viewer=env_map.get("ENABLE_VIEWER", "").lower() in {"1", "true", "yes"},
        env_file_path=env_file_path if env_file_path and env_file_path.exists() else None,
        dev_src_path=dev_src_path if dev_src_path and dev_src_path.exists() else None,
        emulator_timeout=emulator_timeout,
        http_proxy=env_map.get("http_proxy") or env_map.get("HTTP_PROXY"),
        https_proxy=env_map.get("https_proxy") or env_map.get("HTTPS_PROXY"),
        no_proxy=env_map.get("no_proxy") or env_map.get("NO_PROXY"),
        entrypoint=entrypoint,
    )

    logger.warning(
        "Rebuilding unhealthy backend container {} with image {} on ports backend={}, viewer={}, adb={}",
        container_name,
        config.image,
        backend_port,
        viewer_port,
        adb_port,
    )
    if not remove_container(container_name, force=True):
        logger.warning("Failed to remove unhealthy container {}", container_name)
        return False

    result = launch_container(
        config,
        wait_ready=True,
        ready_timeout=BACKEND_REBUILD_TIMEOUT_SECONDS,
    )
    if not result.success or not result.ready:
        logger.warning(
            "Rebuilt container {} did not become ready: {}",
            container_name,
            result.error_message,
        )
        return False

    return True


def _recover_backend_env(
    env_url: str,
    container_name: str | None,
    device: str,
    step_wait_time: float,
    suite_family: str,
    enable_mcp: bool,
    seed: int | None,
    env_image: str,
) -> AndroidEnvClient | None:
    """Recover an unhealthy backend by restarting emulator, then rebuilding container."""
    if not container_name:
        logger.warning("Cannot recover unhealthy backend {}; container name is unknown", env_url)
        return None

    for attempt in range(1, BACKEND_EMULATOR_RESTART_ATTEMPTS + 1):
        logger.warning(
            "Restarting emulator inside unhealthy container {} (attempt {}/{})",
            container_name,
            attempt,
            BACKEND_EMULATOR_RESTART_ATTEMPTS,
        )
        if not _restart_emulator_in_container(container_name):
            continue
        try:
            return _init_env_once(
                env_url,
                device,
                step_wait_time,
                suite_family,
                enable_mcp,
                seed=seed,
            )
        except Exception as e:
            logger.warning(
                "Backend {} is still unhealthy after emulator restart attempt {}: {}",
                env_url,
                attempt,
                e,
            )

    if not AUTO_REBUILD_UNHEALTHY_BACKEND:
        return None

    logger.warning(
        "Rebuilding backend container {} after emulator restart attempts failed",
        container_name,
    )
    if not _rebuild_backend_container(container_name, env_image=env_image):
        return None

    try:
        return _init_env_once(
            env_url,
            device,
            step_wait_time,
            suite_family,
            enable_mcp,
            seed=seed,
        )
    except Exception as e:
        logger.warning("Backend {} is still unhealthy after container rebuild: {}", env_url, e)
        return None


def _execute_single_task(
    env: AndroidEnvClient,
    agent: BaseAgent,
    task_name: str,
    max_step: int,
    traj_logger: TrajLogger,
    enable_mcp: bool = False,
    suite_family: str = "memgui_bench",
    log_file_root: str | None = None,
    agent_name: str | None = None,
    attempt_num: int = 1,
    timeout_deadline: float | None = None,
) -> tuple[int, float, str]:
    """Execute a single task and return the number of steps and score.

    Returns:
        tuple[int, float]: (number of steps, score)
    """

    logger.debug(f"max_step: {max_step}")

    if enable_mcp and not isinstance(agent, MCPAgent):
        logger.error(
            "MCP is enabled but agent type is not a MCP agent. Please use a MCP agent type."
        )

    if enable_mcp:
        traj_logger.log_tools(env.tools)
    task_goal = env.get_task_goal(task_type=task_name)

    logger.debug(f"task_goal: {task_goal}")

    step = 0
    obs = env.initialize_task(task_name=task_name)
    agent.initialize(task_goal)

    while True:
        if timeout_deadline is not None and time.monotonic() >= timeout_deadline:
            raise TimeoutError(
                f"Task {task_name} exceeded its timeout before step {step + 1}"
            )

        step += 1

        logger.debug(f"Screenshot captured in step {step}")

        prediction, action = agent.predict(
            {
                "screenshot": obs.screenshot,
                "tool_call": obs.tool_call,
                "ask_user_response": obs.ask_user_response,
            }
        )  # for backward compatibility
        traj_logger.log_traj(
            task_name,
            task_goal,
            step,
            prediction,
            action.model_dump(exclude_none=True),
            obs,
            agent.get_total_token_usage(),
        )
        if prediction is None:
            logger.warning(f"Agent prediction failed in step {step}")
            break

        terminate = False
        logger.debug(f"current step {step}")

        if action.action_type in [ENV_FAIL, FINISHED, UNKNOWN]:
            logger.debug(f"task terminated in step {step} with action {action.action_type}")
            terminate = True
        elif action.action_type in [ANSWER]:
            logger.debug(f"answer triggered, execution action {action}")
            obs = env.execute_action(action)
            terminate = True
        else:
            logger.debug(f"execution action {action}")
            obs = env.execute_action(action)
        if terminate:
            break

        if max_step > 0 and step >= max_step:
            logger.debug("task steps reach max step, terminate")
            break

    if suite_family == "memgui_bench":
        if timeout_deadline is not None and time.monotonic() >= timeout_deadline:
            raise TimeoutError(
                f"Task {task_name} exceeded its timeout before MemGUI-Eval"
            )

        from mobile_world.runtime.utils.memgui_eval import evaluate_memgui_trajectory

        score, reason = evaluate_memgui_trajectory(
            log_file_root=log_file_root or ".",
            task_name=task_name,
            task_traj_dir=traj_logger.log_file_dir,
            agent_name=agent_name or agent.__class__.__name__,
            attempt_num=attempt_num,
        )
    else:
        score, reason = env.get_task_score(task_type=task_name)
    logger.debug(f"task_score: {score}, reason: {reason}")
    traj_logger.log_score(score=score, reason=reason)

    res = env.tear_down_task(task_type=task_name)
    agent.done()
    logger.debug(f"tear_down_task response: {res}")

    return step, score, reason


def _process_task_on_env(
    task_name: str,
    env_queue: Queue,
    agent_type: str,
    model_name: str,
    llm_base_url: str,
    api_key: str | None,
    log_file_root: str,
    max_step: int | None,
    retry_on_device_unhealthy: int = 2,
    device: str = "emulator-5554",
    step_wait_time: float = 1.0,
    seed: int = None,
    env_image: str = DEFAULT_IMAGE,
    enable_mcp: bool = False,
    suite_family: str = "memgui_bench",
    pass_at_k: int = 1,
    task_timeout: int | None = None,
    llm_infra_retries: int = MEMGUI_LLM_INFRA_RETRIES,
    **kwargs,
) -> dict:
    """Process a single task on a specific environment.

    Args:
        task_name: Name of the task to execute
        env_url: URL of the environment to use
        agent_type: Type of agent to create
        model_name: Model name for the agent
        llm_base_url: LLM service base URL
        api_key: API key for LLM service
        log_file_root: Root directory for log files
        max_step: Maximum steps for task execution
        **kwargs: Additional kwargs for agent creation

    Returns:
        dict: Task result containing task_name, success, score, steps, duration_seconds
    """
    thread_id = threading.current_thread().ident
    thread_logs_dir = os.path.join(log_file_root, "_thread_logs")
    os.makedirs(thread_logs_dir, exist_ok=True)
    thread_log_file = os.path.join(thread_logs_dir, f"{task_name}_{thread_id}.log")

    def thread_filter(record):
        return record["extra"].get("thread_id") == thread_id

    thread_handler_id = logger.add(
        thread_log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | container: {extra[container_name]} | {message}",
        level="DEBUG",
        enqueue=True,
        filter=thread_filter,
    )
    env, container_name = env_queue.get()

    try:
        with logger.contextualize(thread_id=thread_id, container_name=container_name):
            attempt_results = []
            task_start_time = time.time()
            timeout_deadline = (
                time.monotonic() + task_timeout
                if task_timeout is not None and task_timeout > 0
                else None
            )
            task_max_step = _resolve_task_max_step(suite_family, task_name, max_step)
            for attempt_num in range(1, pass_at_k + 1):
                if timeout_deadline is not None and time.monotonic() >= timeout_deadline:
                    raise TimeoutError(
                        f"Task {task_name} exceeded its timeout before attempt {attempt_num}"
                    )

                logger.info(
                    "Processing task '{}' attempt {}/{} on environment {}",
                    task_name,
                    attempt_num,
                    pass_at_k,
                    env.base_url,
                )
                if enable_mcp:
                    assert isinstance(env, AndroidMCPEnvClient), (
                        f"env must be a AndroidMCPEnvClient, but got {type(env)}"
                    )
                    try:
                        env.reset_tools(task_type=task_name)
                    except Exception as e:
                        logger.exception(
                            f"Error resetting tools for task {task_name}: {e}"
                        )
                        raise

                agent: BaseAgent | None = None
                traj_logger = None
                infra_retries = 0
                task_steps = 0
                task_score = 0.0
                task_reason = ""
                while True:
                    agent = create_agent(
                        agent_type, model_name, llm_base_url, api_key, env=env, **kwargs
                    )
                    traj_logger = _create_attempt_traj_logger(
                        log_file_root, task_name, attempt_num, pass_at_k
                    )
                    agent.set_llm_request_log_dir(
                        os.path.join(traj_logger.log_file_dir, "agent_llm_requests")
                    )
                    remaining_health_retries = retry_on_device_unhealthy
                    try:
                        while True:
                            try:
                                task_steps, task_score, task_reason = _execute_single_task(
                                    env,
                                    agent,
                                    task_name,
                                    task_max_step,
                                    traj_logger=traj_logger,
                                    enable_mcp=enable_mcp,
                                    suite_family=suite_family,
                                    log_file_root=log_file_root,
                                    agent_name=agent_type,
                                    attempt_num=attempt_num,
                                    timeout_deadline=timeout_deadline,
                                )
                                break
                            except Exception as e:
                                if (
                                    _is_device_unhealthy_error(e)
                                    and remaining_health_retries > 0
                                ):
                                    remaining_health_retries -= 1
                                    logger.warning(
                                        "Device is not healthy; recovering environment "
                                        "before retrying task '{}' (remaining retries: {})",
                                        task_name,
                                        remaining_health_retries,
                                    )
                                    _increment_metadata_counter(
                                        os.path.join(log_file_root, "metadata.json"),
                                        "device_recovery_count",
                                    )
                                    recovered_env = _recover_backend_env(
                                        env.base_url,
                                        container_name,
                                        device,
                                        step_wait_time,
                                        suite_family,
                                        enable_mcp,
                                        seed,
                                        env_image,
                                    )
                                    if recovered_env is not None:
                                        env = recovered_env
                                    elif not _wait_for_env_recovery(env):
                                        logger.warning(
                                            "Environment {} did not recover", env.base_url
                                        )
                                    traj_logger.reset_traj()
                                    continue
                                raise
                        break
                    except Exception as e:
                        if _is_transient_infra_error(e):
                            infra_retries += 1
                            failure_type = (
                                "device_unhealthy"
                                if _is_device_unhealthy_error(e)
                                else "llm_transient"
                            )
                            logger.warning(
                                "Transient infra failure for task '{}' attempt {}/{} "
                                "({}/{}) due to {}: {}",
                                task_name,
                                attempt_num,
                                pass_at_k,
                                infra_retries,
                                llm_infra_retries,
                                failure_type,
                                e,
                            )
                            _safe_tear_down_task(env, agent, task_name)
                            try:
                                traj_logger.reset_traj()
                            except Exception as reset_error:
                                logger.warning(
                                    "Could not reset transient failed trajectory for {}: {}",
                                    task_name,
                                    reset_error,
                                )
                            if infra_retries > llm_infra_retries:
                                failure_path = _write_infra_failure(
                                    log_file_root=log_file_root,
                                    task_name=task_name,
                                    attempt_num=attempt_num,
                                    failure_type=failure_type,
                                    reason=f"{type(e).__name__}: {e}",
                                    infra_retries=infra_retries,
                                    env_url=env.base_url,
                                    container_name=container_name,
                                )
                                _append_infra_failure_metadata(
                                    os.path.join(log_file_root, "metadata.json"),
                                    task_name,
                                    failure_type,
                                )
                                logger.error(
                                    "Task '{}' marked as infra failure at {}",
                                    task_name,
                                    failure_path,
                                )
                                return None

                            if _is_device_unhealthy_error(e):
                                _increment_metadata_counter(
                                    os.path.join(log_file_root, "metadata.json"),
                                    "device_recovery_count",
                                )
                                recovered_env = _recover_backend_env(
                                    env.base_url,
                                    container_name,
                                    device,
                                    step_wait_time,
                                    suite_family,
                                    enable_mcp,
                                    seed,
                                    env_image,
                                )
                                if recovered_env is not None:
                                    env = recovered_env
                                elif not _wait_for_env_recovery(env):
                                    logger.warning(
                                        "Environment {} did not recover", env.base_url
                                    )
                            elif isinstance(e, TransientLLMError) and e.retry_after:
                                time.sleep(min(float(e.retry_after), 30.0))
                            continue

                        logger.exception(
                            f"Error executing task {task_name} attempt {attempt_num}"
                        )
                        task_steps = 0
                        task_score = 0.0
                        task_reason = (
                            f"Task execution failed at attempt {attempt_num}: "
                            f"{type(e).__name__}: {e}"
                        )
                        try:
                            traj_logger.log_score(score=task_score, reason=task_reason)
                        except Exception:
                            _write_failure_result(log_file_root, task_name, task_reason)
                        _safe_tear_down_task(env, agent, task_name)
                        break

                attempt_results.append(
                    {
                        "attempt": attempt_num,
                        "score": task_score,
                        "steps": task_steps,
                        "reason": task_reason,
                        "trajectory_dir": traj_logger.log_file_dir,
                    }
                )
                if pass_at_k > 1 and _is_successful_score(task_score):
                    logger.info(
                        "Task '{}' succeeded at attempt {}/{}; skipping remaining attempts",
                        task_name,
                        attempt_num,
                        pass_at_k,
                    )
                    break

            task_duration = time.time() - task_start_time
            if pass_at_k > 1:
                task_score, task_reason = _write_pass_at_k_result(
                    log_file_root, task_name, pass_at_k, attempt_results
                )
            else:
                task_score = float(attempt_results[0]["score"]) if attempt_results else 0.0
                task_reason = attempt_results[0].get("reason", "") if attempt_results else ""
            task_success = task_score > 0.0

            logger.info(
                "Task '{}' completed on {}: success={}, score={}, attempts={}, duration={:.1f}s",
                task_name,
                env.base_url,
                task_success,
                task_score,
                len(attempt_results),
                task_duration,
            )

            return {
                "task_name": task_name,
                "score": task_score,
                "reason": task_reason,
                "pass_at_k": pass_at_k,
                "attempts": attempt_results,
            }
    except Exception as e:
        with logger.contextualize(thread_id=thread_id, container_name=container_name):
            logger.exception("Task '{}' failed before completion", task_name)
        task_reason = f"Task failed before completion: {type(e).__name__}: {e}"
        task_score, task_reason = _write_failure_result(
            log_file_root, task_name, task_reason
        )
        return {
            "task_name": task_name,
            "score": task_score,
            "reason": task_reason,
            "pass_at_k": pass_at_k,
            "attempts": [],
        }
    finally:
        # Remove the thread-specific handler
        logger.remove(thread_handler_id)
        env_queue.put((env, container_name))


def _make_env_client(
    env_url: str, device: str, step_wait_time: float, suite_family: str, enable_mcp: bool,
) -> AndroidEnvClient:
    if enable_mcp:
        return AndroidMCPEnvClient(env_url, device, step_wait_time=step_wait_time)
    return AndroidEnvClient(env_url, device, step_wait_time=step_wait_time)


def _init_env_once(
    env_url: str, device: str, step_wait_time: float, suite_family: str, enable_mcp: bool,
    seed: int = None,
) -> AndroidEnvClient:
    """Initialize one environment once without waiting for server-side recovery loops."""
    env = _make_env_client(env_url, device, step_wait_time, suite_family, enable_mcp)
    env.switch_suite_family(suite_family, seed=seed)
    return env


def _init_env(
    env_url: str, device: str, step_wait_time: float, suite_family: str, enable_mcp: bool,
    seed: int = None,
) -> AndroidEnvClient:
    """Initialize the environment."""
    env = _make_env_client(env_url, device, step_wait_time, suite_family, enable_mcp)

    for attempt in range(3):
        try:
            env.switch_suite_family(suite_family, seed=seed)
            return env
        except Exception as e:
            if "Device is not healthy" not in str(e) or attempt == 2:
                raise
            logger.warning(
                "Environment {} is unhealthy during initialization; waiting for recovery "
                "before retry {}/3",
                env_url,
                attempt + 2,
            )
            _wait_for_env_recovery(env)
    return env


def _init_env_result(
    index: int,
    env_url: str,
    device: str,
    step_wait_time: float,
    suite_family: str,
    enable_mcp: bool,
    seed: int = None,
    container_name: str | None = None,
    env_image: str = DEFAULT_IMAGE,
) -> tuple[int, AndroidEnvClient | None, str | None]:
    """Initialize one backend and capture unhealthy failures for pool filtering."""
    try:
        return (
            index,
            _init_env_once(env_url, device, step_wait_time, suite_family, enable_mcp, seed=seed),
            None,
        )
    except Exception as e:
        if _is_device_unhealthy_error(e):
            recovered_env = _recover_backend_env(
                env_url,
                container_name,
                device,
                step_wait_time,
                suite_family,
                enable_mcp,
                seed,
                env_image,
            )
            if recovered_env is not None:
                return index, recovered_env, None
        logger.warning("Skipping unhealthy environment {} during initialization: {}", env_url, e)
        return index, None, f"{env_url}: {type(e).__name__}: {e}"


def _initialize_env_pool(
    aw_urls: list[str],
    container_names: list[str] | None,
    device: str,
    step_wait_time: float,
    suite_family: str,
    enable_mcp: bool,
    seed: int | None = None,
    max_concurrency: int | None = None,
    env_image: str = DEFAULT_IMAGE,
) -> tuple[list[AndroidEnvClient], list[str | None]]:
    """Initialize all candidate backends and keep only healthy environments."""
    if not aw_urls:
        return [], []

    init_jobs = min(max_concurrency if max_concurrency is not None else len(aw_urls), len(aw_urls))
    init_results = Parallel(n_jobs=init_jobs, backend="threading")(
        delayed(_init_env_result)(
            index,
            env_url,
            device,
            step_wait_time,
            suite_family,
            enable_mcp,
            seed=seed,
            container_name=container_names[index]
            if container_names and index < len(container_names)
            else None,
            env_image=env_image,
        )
        for index, env_url in enumerate(aw_urls)
    )

    envs: list[AndroidEnvClient] = []
    healthy_container_names: list[str | None] = []
    failed_envs: list[str] = []

    for index, env, error in sorted(init_results, key=lambda item: item[0]):
        if env is None:
            if error:
                failed_envs.append(error)
            continue

        envs.append(env)
        healthy_container_names.append(
            container_names[index] if container_names and index < len(container_names) else None
        )

    if failed_envs:
        logger.warning(
            "Ignoring {} unhealthy backend environment(s): {}",
            len(failed_envs),
            failed_envs,
        )

    if not envs:
        details = "; ".join(failed_envs) if failed_envs else "no backend URLs were available"
        raise RuntimeError(
            "No healthy backend environments available after initialization. "
            f"Please restart containers with `mg env rm && mg env run`. Details: {details}"
        )

    return envs, healthy_container_names


def _get_local_suite_task_list(suite_family: str) -> list[str] | None:
    """Return a local task list when a suite can be enumerated without a backend."""
    if suite_family == "memgui_bench":
        from mobile_world.tasks.memgui_registry import MemGUITaskRegistry

        return MemGUITaskRegistry().list_tasks()
    return None


def run_agent_with_evaluation(
    agent_type: str,
    model_name: str,
    llm_base_url: str,
    log_file_root: str,
    tasks: list[str],
    max_step: int | None = None,
    aw_urls: list[str] | None = None,
    api_key: str | None = None,
    device: str = "emulator-5554",
    step_wait_time: float = 1.0,
    suite_family: str = "memgui_bench",
    seed: int = None,
    env_name_prefix: str = DEFAULT_NAME_PREFIX,
    env_image: str = DEFAULT_IMAGE,
    dry_run: bool = False,
    enable_mcp: bool = False,
    enable_user_interaction: bool = False,
    max_concurrency: int | None = None,
    llm_max_concurrency: int | None = None,
    llm_rate_limit_retries: int | None = None,
    llm_rate_limit_max_wait: float | None = None,
    llm_infra_retries: int | None = None,
    shuffle_tasks: bool = False,
    pass_at_k: int = 1,
    task_file: str | None = None,
    difficulty: str | None = None,
    task_timeout: int | None = None,
    **kwargs,
) -> list[dict]:
    """Run the agent and return the evaluation results.

    Args:
        agent_type: Type of agent to use
        model_name: Model name for the agent
        llm_base_url: LLM service base URL
        log_file_root: Root directory for log files
        tasks: List of task names to execute (empty list for all tasks)
        max_step: Maximum steps for task execution
        aw_urls: List of Android World backend URLs. If None, auto-discover from containers
        api_key: API key for LLM service
        device: Android device ID
        step_wait_time: Wait time after each step
        suite_family: Suite family to use
        **kwargs: Additional kwargs for agent creation

    Returns:
        list[dict]: The evaluation results for each task, containing task_name, success, score, steps, duration_seconds, env_url
    """

    # Write or validate metadata.json at log root for suite family identification.
    ensure_log_root_writable(log_file_root)
    effective_llm_max_concurrency = (
        llm_max_concurrency
        if llm_max_concurrency is not None
        else int(os.getenv("MEMGUI_LLM_MAX_CONCURRENCY", "2"))
    )
    effective_llm_rate_limit_retries = (
        llm_rate_limit_retries
        if llm_rate_limit_retries is not None
        else int(os.getenv("MEMGUI_LLM_RATE_LIMIT_RETRIES", "20"))
    )
    effective_llm_rate_limit_max_wait = (
        llm_rate_limit_max_wait
        if llm_rate_limit_max_wait is not None
        else float(os.getenv("MEMGUI_LLM_RATE_LIMIT_MAX_WAIT", "120"))
    )
    effective_llm_infra_retries = (
        llm_infra_retries
        if llm_infra_retries is not None
        else int(os.getenv("MEMGUI_LLM_INFRA_RETRIES", str(MEMGUI_LLM_INFRA_RETRIES)))
    )
    configure_llm_rate_limits(
        max_concurrency=effective_llm_max_concurrency,
        rate_limit_retries=effective_llm_rate_limit_retries,
        rate_limit_max_wait=effective_llm_rate_limit_max_wait,
        reset_stats=True,
    )
    metadata_path = os.path.join(log_file_root, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            existing = json.load(f)
        if existing.get("suite_family") != suite_family:
            raise ValueError(
                f"Log folder '{log_file_root}' was created with suite_family='{existing.get('suite_family')}', "
                f"but current run uses suite_family='{suite_family}'. "
                f"Use a different --log-file-root or match the suite family."
            )
    else:
        metadata = {
            "suite_family": suite_family,
            "seed": seed,
            "agent_type": agent_type,
            "model_name": model_name,
            "pass_at_k": pass_at_k,
            "task_file": task_file,
            "difficulty": difficulty,
            "step_wait_time": step_wait_time,
            "llm_max_concurrency": effective_llm_max_concurrency,
            "llm_rate_limit_retries": effective_llm_rate_limit_retries,
            "llm_rate_limit_max_wait": effective_llm_rate_limit_max_wait,
            "llm_infra_retries": effective_llm_infra_retries,
            "llm_runtime_stats": get_llm_rate_limit_stats(),
            "infra_failed_tasks": [],
            "infra_failure_counts": {},
            "device_recovery_count": 0,
            "timestamp": datetime.now().isoformat(),
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    if len(tasks) != 0:
        task_list = tasks
    else:
        task_list = _get_local_suite_task_list(suite_family) if dry_run else None

    container_names = None
    envs = None
    needs_backend = task_list is None or not dry_run
    if needs_backend and (aw_urls is None or len(aw_urls) == 0):
        logger.info("No backend URLs specified, auto-discovering from containers...")
        aw_urls, container_names = discover_backends(image_filter=env_image, prefix=env_name_prefix)
        logger.info("Container names: {}", container_names)
        if not aw_urls:
            logger.error("No backend URLs found. Please start containers or specify --aw-host")
            return [], []

    if aw_urls:
        logger.info("Using {} backend URL(s): {}", len(aw_urls), aw_urls)
    elif dry_run:
        logger.info("Dry run mode without backend URLs; no environment will be initialized")

    if task_list is None:
        assert aw_urls is not None
        envs, container_names = _initialize_env_pool(
            aw_urls,
            container_names,
            device,
            step_wait_time,
            suite_family,
            enable_mcp,
            seed=seed,
            max_concurrency=max_concurrency,
            env_image=env_image,
        )
        task_list = envs[0].get_suite_task_list(
            enable_mcp=enable_mcp,
            enable_user_interaction=enable_user_interaction,
        )

    logger.info("Task list: {} ({} tasks)", task_list, len(task_list))
    _update_log_metadata(
        metadata_path,
        {
            "suite_family": suite_family,
            "seed": seed,
            "agent_type": agent_type,
            "model_name": model_name,
            "pass_at_k": pass_at_k,
            "task_file": task_file,
            "difficulty": difficulty,
            "step_wait_time": step_wait_time,
            "llm_max_concurrency": effective_llm_max_concurrency,
            "llm_rate_limit_retries": effective_llm_rate_limit_retries,
            "llm_rate_limit_max_wait": effective_llm_rate_limit_max_wait,
            "llm_infra_retries": effective_llm_infra_retries,
            "llm_runtime_stats": get_llm_rate_limit_stats(),
            "task_list": task_list,
            "task_count": len(task_list),
            "task_selection": "selected" if tasks else "all",
            "run_status": "running",
            "run_started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        },
    )

    try:
        if suite_family == "memgui_bench":
            finished_task_list, finished_scores = _scan_finished_memgui_pass_at_k_tasks(
                log_file_root, task_list, pass_at_k
            )
            logger.info(
                "MemGUI resume enabled; skipping existing successful or completed pass@{} tasks",
                pass_at_k,
            )
        else:
            finished_task_list, finished_scores = scan_finished_tasks(
                log_file_root, task_list
            )
        logger.info(
            "Finished task list: {} ({} tasks)", finished_task_list, len(finished_task_list)
        )

        task_list = [task for task in task_list if task not in finished_task_list]
        logger.info("Remaining tasks to execute: {} ({} tasks)", task_list, len(task_list))

        if shuffle_tasks:
            random.shuffle(task_list)

        if dry_run:
            logger.info("Dry run mode, skipping environment initialization and task execution")
            task_results = []
        else:
            assert aw_urls is not None
            if envs is None:
                envs, container_names = _initialize_env_pool(
                    aw_urls,
                    container_names,
                    device,
                    step_wait_time,
                    suite_family,
                    enable_mcp,
                    seed=seed,
                    max_concurrency=max_concurrency,
                    env_image=env_image,
                )

            num_envs = len(envs)
            logger.info("Distributing {} tasks across {} environment(s)", len(task_list), num_envs)

            env_queue = Queue[tuple[AndroidEnvClient, str | None]](maxsize=num_envs)
            for i, env in enumerate(envs):
                env_queue.put((env, container_names[i] if container_names else None))

            logger.info("Starting parallel task execution with threading backend...")

            task_results = Parallel(
                n_jobs=min(
                    max_concurrency if max_concurrency is not None else num_envs, num_envs
                ),
                backend="threading",
            )(
                delayed(_process_task_on_env)(
                    task_name=task_name,
                    env_queue=env_queue,
                    agent_type=agent_type,
                    model_name=model_name,
                    llm_base_url=llm_base_url,
                    api_key=api_key,
                    log_file_root=log_file_root,
                    max_step=max_step,
                    enable_mcp=enable_mcp,
                    suite_family=suite_family,
                    pass_at_k=pass_at_k,
                    task_timeout=task_timeout,
                    llm_infra_retries=effective_llm_infra_retries,
                    device=device,
                    step_wait_time=step_wait_time,
                    seed=seed,
                    env_image=env_image,
                    **kwargs,
                )
                for task_name in task_list
            )

        task_list_with_no_results = [
            task_name
            for task_name, task_result in zip(task_list, task_results)
            if task_result is None
        ]
        logger.info(f"Task with no results count: {len(task_list_with_no_results)}")
        success_task_results = [task_result for task_result in task_results if task_result is not None]

        for finished_task_name, finished_score in zip(finished_task_list, finished_scores):
            success_task_results.append(
                {
                    "task_name": finished_task_name,
                    "score": finished_score,
                }
            )

        _update_log_metadata(
            metadata_path,
            {
                "run_status": "completed",
                "run_completed_at": datetime.now().isoformat(),
                "task_with_no_results": task_list_with_no_results,
                "llm_runtime_stats": get_llm_rate_limit_stats(),
                "updated_at": datetime.now().isoformat(),
            },
        )

        return (success_task_results, task_list_with_no_results)
    except BaseException as e:
        run_status = "interrupted" if isinstance(e, (KeyboardInterrupt, SystemExit)) else "failed"
        _update_log_metadata(
            metadata_path,
            {
                "run_status": run_status,
                "run_completed_at": datetime.now().isoformat(),
                "run_error_type": type(e).__name__,
                "run_error": str(e),
                "llm_runtime_stats": get_llm_rate_limit_stats(),
                "updated_at": datetime.now().isoformat(),
            },
        )
        raise
