import json
import os
import random
import threading
import time
from datetime import datetime
from functools import lru_cache
from queue import Queue

from dotenv import load_dotenv
from joblib import Parallel, delayed
from loguru import logger

from mobile_world.agents.base import BaseAgent, MCPAgent
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
            f"successful_attempts={successful_attempts}"
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
    enable_mcp: bool = False,
    suite_family: str = "memgui_bench",
    pass_at_k: int = 1,
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
            task_max_step = _resolve_task_max_step(suite_family, task_name, max_step)
            for attempt_num in range(1, pass_at_k + 1):
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
                        logger.exception(f"Error resetting tools for task {task_name}: {e}")
                        return None

                agent = create_agent(
                    agent_type, model_name, llm_base_url, api_key, env=env, **kwargs
                )
                traj_logger = _create_attempt_traj_logger(
                    log_file_root, task_name, attempt_num, pass_at_k
                )
                remaining_health_retries = retry_on_device_unhealthy
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
                        )
                        break
                    except Exception as e:
                        if (
                            "Device is not healthy" in str(e)
                            and remaining_health_retries > 0
                        ):
                            logger.warning("Device is not healthy, retrying...")
                            time.sleep(20)
                            remaining_health_retries -= 1
                            traj_logger.reset_traj()
                            continue
                        logger.exception(
                            f"Error executing task {task_name} attempt {attempt_num}"
                        )
                        return None

                attempt_results.append(
                    {
                        "attempt": attempt_num,
                        "score": task_score,
                        "steps": task_steps,
                        "reason": task_reason,
                        "trajectory_dir": traj_logger.log_file_dir,
                    }
                )

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
    finally:
        # Remove the thread-specific handler
        logger.remove(thread_handler_id)
        env_queue.put((env, container_name))


def _init_env(
    env_url: str, device: str, step_wait_time: float, suite_family: str, enable_mcp: bool,
    seed: int = None,
) -> AndroidEnvClient:
    """Initialize the environment."""
    if enable_mcp:
        env = AndroidMCPEnvClient(env_url, device, step_wait_time=step_wait_time)
    else:
        env = AndroidEnvClient(env_url, device, step_wait_time=step_wait_time)
    env.switch_suite_family(suite_family, seed=seed)
    return env


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
    shuffle_tasks: bool = False,
    pass_at_k: int = 1,
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
        envs = Parallel(
            n_jobs=min(max_concurrency if max_concurrency is not None else len(aw_urls), len(aw_urls)),
            backend="threading",
        )(
            delayed(_init_env)(env_url, device, step_wait_time, suite_family, enable_mcp, seed=seed)
            for env_url in aw_urls
        )
        task_list = envs[0].get_suite_task_list(
            enable_mcp=enable_mcp,
            enable_user_interaction=enable_user_interaction,
        )

    logger.info("Task list: {} ({} tasks)", task_list, len(task_list))

    if pass_at_k > 1:
        finished_task_list, finished_scores = [], []
        logger.info("pass@{} enabled; skipping result.txt based task skip", pass_at_k)
    else:
        finished_task_list, finished_scores = scan_finished_tasks(log_file_root, task_list)
    logger.info("Finished task list: {} ({} tasks)", finished_task_list, len(finished_task_list))

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
            envs = Parallel(
                n_jobs=min(max_concurrency if max_concurrency is not None else len(aw_urls), len(aw_urls)),
                backend="threading",
            )(
                delayed(_init_env)(env_url, device, step_wait_time, suite_family, enable_mcp, seed=seed)
                for env_url in aw_urls
            )

        num_envs = len(envs)
        logger.info("Distributing {} tasks across {} environment(s)", len(task_list), num_envs)

        env_queue = Queue[tuple[AndroidEnvClient, str | None]](maxsize=num_envs)
        for i, env in enumerate(envs):
            env_queue.put((env, container_names[i] if container_names else None))

        logger.info("Starting parallel task execution with threading backend...")

        task_results = Parallel(
            n_jobs=min(max_concurrency if max_concurrency is not None else num_envs, num_envs),
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
                **kwargs,
            )
            for task_name in task_list
        )

    task_list_with_no_results = [
        task_name for task_name, task_result in zip(task_list, task_results) if task_result is None
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

    return (success_task_results, task_list_with_no_results)
