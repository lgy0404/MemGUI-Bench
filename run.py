import os
import yaml
import argparse
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import shutil

from framework import utils
from framework.progress_monitor import initialize_timing
from framework.realtime_metrics import (
    calculate_and_save_metrics,
    save_leaderboard_result,
)
from config_loader import load_config

load_dotenv(verbose=True, override=True)

# Load configuration with mode presets applied
config = load_config(verbose=True)

# 创建评估任务执行器
eval_executor = ThreadPoolExecutor(max_workers=config.get("MAX_EVAL_SUBPROCESS", 8))

# 命令行参数解析
parser = argparse.ArgumentParser()
parser.add_argument("--agents", type=str, default=config["AGENT_NAME"])
parser.add_argument(
    "--mode", type=str, default="full", choices=["full", "exec", "eval"]
)
parser.add_argument("--session_id", type=str, default=config["SESSION_ID"])
parser.add_argument("--task_id", type=str, default=None)
parser.add_argument("--no_concurrent", action="store_true")
parser.add_argument(
    "--setup_avd",
    "--setup-avd",
    dest="setup_avd",
    action=argparse.BooleanOptionalAction,
    default=True,
)
parser.add_argument("--setup_emulator", action="store_true")
parser.add_argument("--skip_key_components", type=bool, default=True)
parser.add_argument("--base_url", "--base-url", dest="base_url", type=str, default=None)
parser.add_argument("--api_key", "--api-key", dest="api_key", type=str, default=None)
parser.add_argument(
    "--memgui_api_key", "--memgui-api-key", dest="memgui_api_key", type=str, default=None
)
parser.add_argument("--model_name", "--model-name", dest="model_name", type=str, default=None)
parser.add_argument(
    "--num_emulators", "--num-emulators", dest="num_emulators", type=int, default=None
)
parser.add_argument("--results_dir", "--results-dir", dest="results_dir", type=str, default=None)
parser.add_argument("--dataset", dest="dataset", type=str, default=None)
parser.add_argument(
    "--reasoning_mode", type=str, default="direct", choices=["result_only", "direct"]
)
parser.add_argument(
    "--action_mode",
    type=str,
    default="with_action",
    choices=["no_action", "with_action", "text_action"],
)
parser.add_argument("--overwrite", action="store_true")
parser.add_argument("--overwrite_session", action="store_true")
parser.add_argument(
    "--max_attempts",
    type=int,
    default=config["MAX_ATTEMPTS"],
    help="Maximum number of attempts for each task.",
)
args = parser.parse_args()

if args.base_url:
    config["BASE_URL"] = args.base_url
    for url_key in [
        "QWEN_BASE_URL",
        "MEMGUI_STEP_DESC_BASE_URL",
        "MEMGUI_FINAL_DECISION_BASE_URL",
    ]:
        config[url_key] = args.base_url
if args.api_key:
    config["OPENAI_API_KEY"] = args.api_key
    config["QWEN_API_KEY"] = args.api_key
if args.memgui_api_key:
    config["MEMGUI_API_KEY"] = args.memgui_api_key
if args.model_name:
    config["QWEN_MODEL"] = args.model_name
if args.num_emulators is not None:
    config["NUM_OF_EMULATOR"] = args.num_emulators
if args.results_dir:
    config["RESULTS_DIR"] = args.results_dir
if args.dataset:
    config["DATASET_PATH"] = args.dataset

# 初始化输出目录和结果DataFrame
output_dir = utils.setup_output_directory(
    os.path.join(os.getcwd(), config["RESULTS_DIR"]),
    args.session_id,
    args.overwrite_session,
)

# Save config.yaml to session directory for reproducibility
config_backup_path = os.path.join(output_dir, "config.yaml")
try:
    # Load the original config file path
    config_file_path = os.path.join(os.getcwd(), "config.yaml")
    if os.path.exists(config_file_path):
        shutil.copy2(config_file_path, config_backup_path)
        print(f"Config saved to: {config_backup_path}")
    else:
        # If config.yaml doesn't exist, save the loaded config dict
        with open(config_backup_path, "w", encoding="utf-8") as f:
            yaml.dump(
                config, f, default_flow_style=False, allow_unicode=True, sort_keys=False
            )
        print(f"Config saved to: {config_backup_path} (from loaded config)")
except Exception as e:
    print(f"Warning: Failed to save config.yaml to session directory: {e}")

result_overwrite = args.overwrite
print("Overwrite:", result_overwrite)

# 设置设备
if args.mode in ("full", "exec"):
    if args.setup_avd:
        utils.setup_avd(
            config["SYS_AVD_HOME"],
            os.path.join(os.getcwd(), config["SOURCE_AVD_HOME"]),
            config["SOURCE_AVD_NAME"],
            config["NUM_OF_EMULATOR"],
            config["ANDROID_SDK_PATH"],
        )
        devices = utils.setup_emulator(
            config["EMULATOR_PATH"],
            config["SOURCE_AVD_NAME"],
            config["NUM_OF_EMULATOR"],
        )
    elif args.setup_emulator:
        devices = utils.setup_emulator(
            config["EMULATOR_PATH"],
            config["SOURCE_AVD_NAME"],
            config["NUM_OF_EMULATOR"],
        )
    else:
        devices = utils.setup_devices()
else:
    devices = [{"serial": "eval_mode"}]

# 确定代理和任务范围
if args.agents is None:
    agent_scope = [agent_config["NAME"] for agent_config in config["AGENTS"]]
else:
    agent_scope = args.agents.split(",")

# 验证代理名称
if args.mode in ("full", "exec"):
    for agent_name in agent_scope:
        utils.get_agent(agent_name)(config)

# 设置结果CSV
results_df = utils.setup_results_csv(
    output_dir,
    config["DATASET_PATH"],
    agent_scope,
    args.max_attempts,
    args.reasoning_mode,
    args.action_mode,
)
config["output_dir"] = output_dir
# Only override API keys if environment variables are set, otherwise keep config.yaml values
if os.getenv("OPENAI_API_KEY") and not args.api_key:
    config["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
if os.getenv("QWEN_API_KEY") and not args.api_key:
    config["QWEN_API_KEY"] = os.getenv("QWEN_API_KEY")

# 确定任务范围
if args.task_id is None:
    task_scope = list(results_df.itertuples(index=False))
else:
    task_rows = results_df[results_df["task_identifier"] == args.task_id]
    if task_rows.empty:
        print(f"Error: Task ID '{args.task_id}' not found in the dataset.")
        exit(1)
    task_scope = list(task_rows.itertuples(index=False))

subprocess_list = []  # 存储并发子进程的列表


def print_realtime_progress(trigger=""):
    """
    包装函数：计算并打印实时指标

    使用 realtime_metrics 模块计算所有指标（来自 results_summary 的方案），
    并实时保存到文件中。
    """
    # 使用新的实时指标模块计算并保存所有指标
    calculate_and_save_metrics(
        output_dir=output_dir,
        max_attempts=args.max_attempts,
        trigger=trigger,
        print_summary=True,
        save_to_file=True,
    )


def get_task_number(task_identifier):
    """
    从task_identifier中提取数字编号。
    例如: "001-FindProductAndFilter" -> 1
         "003-RecordAndNameAudio" -> 3

    Returns:
        int: 任务编号，如果无法提取则返回-1
    """
    parts = task_identifier.split("-", 1)
    if parts[0].isdigit():
        return int(parts[0])
    return -1


def group_tasks_by_type(task_scope, num_devices=2):
    """
    将任务分组以分配到不同设备。

    新的分配策略（优先级从高到低）：
    1. 优先保证：相同 task_app 的任务分配到不同 emulator
    2. 次要保证：相同 original_task_id 的任务分配到不同 emulator
    3. 充分利用所有 emulator

    算法：贪心分配，每次选择当前负载最小的 emulator

    Args:
        task_scope: 任务列表
        num_devices: 可用设备数量

    Returns:
        List[List]: 每个子列表包含分配到同一设备的任务
    """
    from collections import defaultdict

    # 检查是否有 task_app 和 original_task_id 属性
    has_task_app = any(
        hasattr(t, "task_app") and getattr(t, "task_app", None) for t in task_scope
    )
    has_original_task_id = any(
        hasattr(t, "original_task_id") and getattr(t, "original_task_id", None)
        for t in task_scope
    )

    # 如果没有特殊属性，简单地平均分配
    if not has_task_app and not has_original_task_id:
        groups = [[] for _ in range(num_devices)]
        for i, task in enumerate(task_scope):
            groups[i % num_devices].append(task)
        return [g for g in groups if g]

    # 初始化设备组
    groups = [[] for _ in range(num_devices)]

    # 跟踪每个设备上已有的 task_app 和 original_task_id
    device_task_apps = [set() for _ in range(num_devices)]
    device_original_ids = [set() for _ in range(num_devices)]

    # 按 task_app 分组任务（如果有的话）
    if has_task_app:
        tasks_by_app = defaultdict(list)
        for task in task_scope:
            app = getattr(task, "task_app", None)
            if app:
                tasks_by_app[app].append(task)
        else:
            tasks_by_app["_no_app_"].append(task)

        # 对每个 app 的任务进行分配
        for app, tasks in sorted(tasks_by_app.items()):
            # 对于同一个 app 的任务，尽量分配到不同的 emulator
            for task in tasks:
                # 找到最适合的设备：
                # 1. 优先选择没有这个 app 的设备
                # 2. 如果有 original_task_id，也优先选择没有这个 id 的设备
                # 3. 选择任务数最少的设备

                best_device = None
                best_score = None

                for device_idx in range(num_devices):
                    # 计算分配得分（越小越好）
                    score = 0

                    # 检查 task_app 冲突（优先级最高）
                    task_app_value = getattr(task, "task_app", None)
                    if (
                        task_app_value
                        and task_app_value in device_task_apps[device_idx]
                    ):
                        score += 1000  # 高惩罚

                    # 检查 original_task_id 冲突（优先级次之）
                    origin_id = getattr(task, "original_task_id", None)
                    if origin_id and origin_id in device_original_ids[device_idx]:
                        score += 100  # 中等惩罚

                    # 任务数量（用于负载均衡）
                    score += len(groups[device_idx])

                    if best_score is None or score < best_score:
                        best_score = score
                        best_device = device_idx

                # 分配到最佳设备
                groups[best_device].append(task)

                # 更新跟踪信息
                task_app_value = getattr(task, "task_app", None)
                if task_app_value:
                    device_task_apps[best_device].add(task_app_value)

                origin_id = getattr(task, "original_task_id", None)
                if origin_id:
                    device_original_ids[best_device].add(origin_id)

    elif has_original_task_id:
        # 如果只有 original_task_id，按它分配
        for task in task_scope:
            origin_id = getattr(task, "original_task_id", None)

            # 找到最适合的设备
            best_device = None
            best_score = None

            for device_idx in range(num_devices):
                score = 0

                # 检查 original_task_id 冲突
                if origin_id and origin_id in device_original_ids[device_idx]:
                    score += 100

                # 任务数量
                score += len(groups[device_idx])

                if best_score is None or score < best_score:
                    best_score = score
                    best_device = device_idx

            # 分配到最佳设备
            groups[best_device].append(task)

            # 更新跟踪信息
            if origin_id:
                device_original_ids[best_device].add(origin_id)

    # 移除空组
    groups = [g for g in groups if g]

    # 打印分配信息
    print("\n" + "=" * 80)
    print("Task Distribution to Emulators")
    print("=" * 80)

    if has_task_app:
        # 统计所有唯一的 task_app
        all_apps = set()
        for task in task_scope:
            app = getattr(task, "task_app", None)
            if app:
                all_apps.add(app)
        print(f"Total unique task_apps: {len(all_apps)}")

    if has_original_task_id:
        # 统计所有唯一的 original_task_id
        all_origins = set()
        for task in task_scope:
            origin = getattr(task, "original_task_id", None)
            if origin:
                all_origins.add(origin)
        print(f"Total unique original_task_ids: {len(all_origins)}")

    print(f"Total tasks: {len(task_scope)}")
    print(f"Number of emulator groups: {len(groups)}")
    print("-" * 80)

    # 详细统计每个设备的分配情况
    for i, group in enumerate(groups):
        print(f"\nEmulator {i}:")
        print(f"  Total tasks: {len(group)}")

        if has_task_app:
            # 统计这个设备上的 task_app
            apps_in_group = set()
            for task in group:
                app = getattr(task, "task_app", None)
                if app:
                    apps_in_group.add(app)
            print(f"  Unique task_apps: {len(apps_in_group)}")

            # 检查 task_app 冲突
            app_counts = defaultdict(int)
            for task in group:
                app = getattr(task, "task_app", None)
                if app:
                    app_counts[app] += 1
            conflicts = {app: count for app, count in app_counts.items() if count > 1}
            if conflicts:
                print(f"  ⚠ task_app conflicts: {conflicts}")

        if has_original_task_id:
            # 统计这个设备上的 original_task_id
            origins_in_group = set()
            for task in group:
                origin = getattr(task, "original_task_id", None)
                if origin:
                    origins_in_group.add(origin)
            print(f"  Unique original_task_ids: {len(origins_in_group)}")

            # 检查 original_task_id 冲突
            origin_counts = defaultdict(int)
            for task in group:
                origin = getattr(task, "original_task_id", None)
                if origin:
                    origin_counts[origin] += 1
            conflicts = {
                origin: count for origin, count in origin_counts.items() if count > 1
            }
            if conflicts:
                print(f"  ⚠ original_task_id conflicts: {conflicts}")

    print("=" * 80 + "\n")

    return groups


def check_attempt_success(
    output_dir, task_identifier, agent_name, attempt, reasoning_mode, action_mode
):
    """
    检查某个attempt是否成功完成（evaluation_summary.json中final_result为1）

    Returns:
        bool: True表示成功，False表示失败或未评估
    """
    import json

    attempt_dir = os.path.join(
        output_dir, task_identifier, agent_name, f"attempt_{attempt}"
    )
    eval_summary_path = os.path.join(attempt_dir, "evaluation_summary.json")

    if not os.path.exists(eval_summary_path):
        return False

    try:
        with open(eval_summary_path, "r") as f:
            eval_data = json.load(f)
            return eval_data.get("final_result", 0) == 1
    except Exception as e:
        print(f"Error reading evaluation summary for attempt {attempt}: {e}")
        return False


def run_task_benchmark(agent_name, task, subprocess_list, devices):
    """
    执行任务的benchmark逻辑：执行多次attempt直到成功或达到最大次数
    """
    print(
        f"=== Starting benchmark execution for task {task.task_identifier} with {args.max_attempts} attempts ==="
    )

    # 首先检查是否已经有成功的attempt（不需要执行所有attempts）
    if not result_overwrite:
        for attempt in range(1, args.max_attempts + 1):
            if check_attempt_success(
                output_dir,
                task.task_identifier,
                agent_name,
                attempt,
                args.reasoning_mode,
                args.action_mode,
            ):
                print(
                    f"Task {task.task_identifier} already has a successful attempt ({attempt}). Skipping task execution."
                )
                return

    # 检查任务是否已经完全完成
    task_fully_completed = utils.is_task_fully_completed(
        output_dir,
        task.task_identifier,
        agent_name,
        args.max_attempts,
        args.reasoning_mode,
        args.action_mode,
    )

    if task_fully_completed:
        if result_overwrite:
            print(
                f"Task {task.task_identifier} is already fully completed. Overwriting results due to --overwrite flag."
            )
            utils.clear_task_results(
                output_dir,
                task.task_identifier,
                agent_name,
                args.max_attempts,
                args.reasoning_mode,
                args.action_mode,
            )
        else:
            print(
                f"Task {task.task_identifier} is already fully completed. Skipping due to --overwrite flag not set."
            )
            return

    agent = utils.get_agent(agent_name=agent_name)(config)

    # Rollout逻辑：执行所有attempts，每个attempt使用不同的emulator
    for attempt in range(1, args.max_attempts + 1):
        print(
            f"--- Processing attempt {attempt}/{args.max_attempts} for task {task.task_identifier} ---"
        )

        # 选择设备：循环使用可用设备，确保不同attempt使用不同设备
        device_index = (attempt - 1) % len(devices)
        device = devices[device_index]

        print(f"Using device {device['serial']} for attempt {attempt}")

        # 检查当前attempt的状态
        attempt_status = utils.get_attempt_status(
            output_dir,
            task.task_identifier,
            agent_name,
            attempt,
            args.reasoning_mode,
            args.action_mode,
        )

        print(f"Attempt {attempt} status: {attempt_status}")

        if attempt_status == "executed_and_evaluated":
            if result_overwrite:
                print(
                    f"Attempt {attempt} already completed but overwriting due to --overwrite flag."
                )
            else:
                print(f"Attempt {attempt} is already executed and evaluated. Skipping.")
                continue
        elif attempt_status == "emulator_crash":
            # 检测到emulator中断导致的失败，清空文件夹并重试
            attempt_dir = os.path.join(
                output_dir, task.task_identifier, agent_name, f"attempt_{attempt}"
            )
            print(
                f"[Emulator Crash Recovery] Attempt {attempt} failed due to emulator crash. "
                f"Clearing directory and retrying..."
            )
            if os.path.exists(attempt_dir):
                shutil.rmtree(attempt_dir)
                print(f"Cleared crashed attempt directory: {attempt_dir}")

            # 重启设备
            if args.setup_avd:
                print(f"Restarting device {device['serial']} after emulator crash...")
                if not utils.check_and_restart_device_if_needed(
                    device, config["EMULATOR_PATH"], config["SOURCE_AVD_NAME"]
                ):
                    print(
                        f"Failed to restart device {device['serial']} after crash, skipping attempt {attempt}"
                    )
                    continue
            # 继续执行这个attempt（不continue，让它走到下面的执行逻辑）
        elif attempt_status == "executed_not_evaluated":
            print(
                f"Attempt {attempt} is executed but not evaluated. Performing evaluation only."
            )
            # 只执行评估
            if args.mode == "full":
                print(f"Evaluating task {task.task_identifier}, attempt {attempt}...")
                utils.immediate_evaluate_and_update_pass_at_k(
                    output_dir,
                    task.task_identifier,
                    agent_name,
                    attempt,
                    args.reasoning_mode,
                    args.action_mode,
                    result_overwrite,
                )

                # 检查评估后是否成功，如果成功则提前结束
                if check_attempt_success(
                    output_dir,
                    task.task_identifier,
                    agent_name,
                    attempt,
                    args.reasoning_mode,
                    args.action_mode,
                ):
                    print(
                        f"*** Task {task.task_identifier} attempt {attempt} succeeded (final_result=1). "
                        f"Skipping remaining attempts ({attempt + 1}-{args.max_attempts}). ***"
                    )
                    break
            continue

        # 对于需要执行的attempt（包括emulator_crash恢复后的重试），确保设备准备就绪
        if args.setup_avd:
            print(
                f"Ensuring device {device['serial']} is ready for attempt {attempt}..."
            )
            if not utils.check_and_restart_device_if_needed(
                device, config["EMULATOR_PATH"], config["SOURCE_AVD_NAME"]
            ):
                print(
                    f"Failed to prepare device {device['serial']}, skipping attempt {attempt}"
                )
                continue

        # 执行任务
        if args.mode in ("full", "exec"):
            attempt_dir = os.path.join(
                output_dir, task.task_identifier, agent_name, f"attempt_{attempt}"
            )

            # 清空attempt文件夹，防止残余文件影响实验
            if os.path.exists(attempt_dir):
                print(f"Clearing existing attempt directory: {attempt_dir}")
                shutil.rmtree(attempt_dir)

            # 创建新的attempt文件夹
            os.makedirs(attempt_dir)
            print(f"Created clean attempt directory: {attempt_dir}")

            # 执行任务，处理重试逻辑
            max_crash_retries = 3

            for retry in range(max_crash_retries + 1):
                print(
                    f"Executing attempt {attempt}, retry {retry + 1}/{max_crash_retries + 1}"
                )

                task_completed, task_exit_code = agent.execute_task(
                    task, device, attempt_dir
                )

                # 如果执行成功或者不是设备崩溃问题，跳出重试循环
                if task_exit_code != 2:
                    break

                # 如果是设备崩溃且还有重试机会
                if retry < max_crash_retries:
                    print(
                        f"Attempt {attempt} failed due to execution error (exit code 2), retrying..."
                    )

                    # 清理失败的attempt目录
                    if os.path.exists(attempt_dir):
                        print(f"Clearing failed attempt directory: {attempt_dir}")
                        shutil.rmtree(attempt_dir)
                        os.makedirs(attempt_dir)

                    # 重启设备
                    if args.setup_avd:
                        if not utils.check_and_restart_device_if_needed(
                            device, config["EMULATOR_PATH"], config["SOURCE_AVD_NAME"]
                        ):
                            print(
                                f"Device {device['serial']} could not be restored. Failing attempt {attempt}"
                            )
                            break
                else:
                    print(
                        f"Max crash retries reached for attempt {attempt}. Recording failure."
                    )

            print(
                f"Finished execution for task: {task.task_identifier}, attempt: {attempt}"
            )
            utils.close_app_activity(device["serial"], None)

            # 保存执行结果
            utils.save_result__completed_execution(
                output_dir,
                task.task_identifier,
                agent_name,
                task_completed,
                task_exit_code,
                device["serial"],
                attempt,
            )
            print_realtime_progress(
                f"Execution Done: {task.task_identifier} (attempt {attempt})"
            )

            # 立即评估（在full模式下）
            if args.mode == "full":
                print(
                    f"Immediately evaluating task {task.task_identifier}, attempt {attempt}..."
                )
                utils.immediate_evaluate_and_update_pass_at_k(
                    output_dir,
                    task.task_identifier,
                    agent_name,
                    attempt,
                    args.reasoning_mode,
                    args.action_mode,
                    result_overwrite,
                )
                print_realtime_progress(
                    f"Evaluation Done: {task.task_identifier} (attempt {attempt})"
                )

                # 检查本次attempt是否成功，如果成功则提前结束
                if check_attempt_success(
                    output_dir,
                    task.task_identifier,
                    agent_name,
                    attempt,
                    args.reasoning_mode,
                    args.action_mode,
                ):
                    print(
                        f"*** Task {task.task_identifier} attempt {attempt} succeeded (final_result=1). "
                        f"Skipping remaining attempts ({attempt + 1}-{args.max_attempts}). ***"
                    )
                    break

    print(f"=== Completed benchmark execution for task {task.task_identifier} ===")


def run_single_attempt(agent_name, task, attempt, device):
    """
    执行单个attempt，用于并发执行
    """
    print(
        f"[Device {device['serial']}] Starting attempt {attempt} for task {task.task_identifier}"
    )

    # 在执行前检查是否已经有其他attempt成功了
    for prev_attempt in range(1, attempt):
        if check_attempt_success(
            output_dir,
            task.task_identifier,
            agent_name,
            prev_attempt,
            args.reasoning_mode,
            args.action_mode,
        ):
            print(
                f"[Device {device['serial']}] Task {task.task_identifier} already has a successful attempt ({prev_attempt}). "
                f"Skipping attempt {attempt}."
            )
            return True  # 返回True表示任务已经完成（通过其他attempt）

    # 检查当前attempt的状态
    attempt_status = utils.get_attempt_status(
        output_dir,
        task.task_identifier,
        agent_name,
        attempt,
        args.reasoning_mode,
        args.action_mode,
    )

    print(f"[Device {device['serial']}] Attempt {attempt} status: {attempt_status}")

    if attempt_status == "executed_and_evaluated":
        if result_overwrite:
            print(
                f"[Device {device['serial']}] Attempt {attempt} already completed but overwriting due to --overwrite flag."
            )
        else:
            print(
                f"[Device {device['serial']}] Attempt {attempt} is already executed and evaluated. Skipping."
            )
            return True
    elif attempt_status == "emulator_crash":
        # 检测到emulator中断导致的失败，清空文件夹并重试
        attempt_dir = os.path.join(
            output_dir, task.task_identifier, agent_name, f"attempt_{attempt}"
        )
        print(
            f"[Device {device['serial']}] [Emulator Crash Recovery] Attempt {attempt} failed due to emulator crash. "
            f"Clearing directory and retrying..."
        )
        if os.path.exists(attempt_dir):
            shutil.rmtree(attempt_dir)
            print(
                f"[Device {device['serial']}] Cleared crashed attempt directory: {attempt_dir}"
            )

        # 重启设备
        if args.setup_avd:
            print(
                f"[Device {device['serial']}] Restarting device after emulator crash..."
            )
            if not utils.check_and_restart_device_if_needed(
                device, config["EMULATOR_PATH"], config["SOURCE_AVD_NAME"]
            ):
                print(
                    f"[Device {device['serial']}] Failed to restart device after crash, skipping attempt {attempt}"
                )
                return False
        # 继续执行这个attempt（不return，让它走到下面的执行逻辑）
    elif attempt_status == "executed_not_evaluated":
        print(
            f"[Device {device['serial']}] Attempt {attempt} is executed but not evaluated. Performing evaluation only."
        )
        # 只执行评估
        if args.mode == "full":
            print(
                f"[Device {device['serial']}] Evaluating task {task.task_identifier}, attempt {attempt}..."
            )
            utils.immediate_evaluate_and_update_pass_at_k(
                output_dir,
                task.task_identifier,
                agent_name,
                attempt,
                args.reasoning_mode,
                args.action_mode,
                result_overwrite,
            )

            # 检查评估后是否成功
            if check_attempt_success(
                output_dir,
                task.task_identifier,
                agent_name,
                attempt,
                args.reasoning_mode,
                args.action_mode,
            ):
                print(
                    f"[Device {device['serial']}] *** Task {task.task_identifier} attempt {attempt} succeeded (final_result=1). ***"
                )
        return True

    # 对于需要执行的attempt（包括emulator_crash恢复后的重试），确保设备准备就绪
    if args.setup_avd:
        print(
            f"[Device {device['serial']}] Ensuring device is ready for attempt {attempt}..."
        )
        if not utils.check_and_restart_device_if_needed(
            device, config["EMULATOR_PATH"], config["SOURCE_AVD_NAME"]
        ):
            print(
                f"[Device {device['serial']}] Failed to prepare device, skipping attempt {attempt}"
            )
            return False

    # 执行任务
    if args.mode in ("full", "exec"):
        attempt_dir = os.path.join(
            output_dir, task.task_identifier, agent_name, f"attempt_{attempt}"
        )

        # 清空attempt文件夹，防止残余文件影响实验
        if os.path.exists(attempt_dir):
            print(
                f"[Device {device['serial']}] Clearing existing attempt directory: {attempt_dir}"
            )
            shutil.rmtree(attempt_dir)

        # 创建新的attempt文件夹
        os.makedirs(attempt_dir)
        print(
            f"[Device {device['serial']}] Created clean attempt directory: {attempt_dir}"
        )

        # 创建agent实例
        agent = utils.get_agent(agent_name=agent_name)(config)

        # 执行任务，处理重试逻辑
        max_crash_retries = 3
        for retry in range(max_crash_retries + 1):
            print(
                f"[Device {device['serial']}] Executing attempt {attempt}, retry {retry + 1}/{max_crash_retries + 1}"
            )

            task_completed, task_exit_code = agent.execute_task(
                task, device, attempt_dir
            )

            # 如果执行成功或者不是设备崩溃问题，跳出重试循环
            if task_exit_code != 2:
                break

            # 如果是设备崩溃且还有重试机会
            if retry < max_crash_retries:
                print(
                    f"[Device {device['serial']}] Attempt {attempt} failed due to execution error (exit code 2), retrying..."
                )

                # 清理失败的attempt目录
                if os.path.exists(attempt_dir):
                    print(
                        f"[Device {device['serial']}] Clearing failed attempt directory: {attempt_dir}"
                    )
                    shutil.rmtree(attempt_dir)
                    os.makedirs(attempt_dir)

                # 重启设备
                if args.setup_avd:
                    if not utils.check_and_restart_device_if_needed(
                        device, config["EMULATOR_PATH"], config["SOURCE_AVD_NAME"]
                    ):
                        print(
                            f"[Device {device['serial']}] Device could not be restored. Failing attempt {attempt}"
                        )
                        break
            else:
                print(
                    f"[Device {device['serial']}] Max crash retries reached for attempt {attempt}. Recording failure."
                )

        print(
            f"[Device {device['serial']}] Finished execution for task: {task.task_identifier}, attempt: {attempt}"
        )
        utils.close_app_activity(device["serial"], None)

        # 保存执行结果
        utils.save_result__completed_execution(
            output_dir,
            task.task_identifier,
            agent_name,
            task_completed,
            task_exit_code,
            device["serial"],
            attempt,
        )
        print_realtime_progress(
            f"Execution Done: {task.task_identifier} (attempt {attempt})"
        )

        # 立即评估（在full模式下）
        if args.mode == "full":
            print(
                f"[Device {device['serial']}] Immediately evaluating task {task.task_identifier}, attempt {attempt}..."
            )
            utils.immediate_evaluate_and_update_pass_at_k(
                output_dir,
                task.task_identifier,
                agent_name,
                attempt,
                args.reasoning_mode,
                args.action_mode,
                result_overwrite,
            )
            print_realtime_progress(
                f"Evaluation Done: {task.task_identifier} (attempt {attempt})"
            )

            # 检查本次attempt是否成功
            if check_attempt_success(
                output_dir,
                task.task_identifier,
                agent_name,
                attempt,
                args.reasoning_mode,
                args.action_mode,
            ):
                print(
                    f"[Device {device['serial']}] *** Task {task.task_identifier} attempt {attempt} succeeded (final_result=1). ***"
                )

    return True


def run_concurrent_benchmark_mode():
    """
    并发benchmark模式：充分利用所有可用设备
    当设备数量 >= max_attempts时，可以并发执行多个任务的不同attempts
    """
    print(
        f"=== Concurrent benchmark mode: {len(devices)} devices, {args.max_attempts} attempts per task ==="
    )

    # 创建任务-attempt组合的工作队列
    work_queue = []
    for agent_name in agent_scope:
        for task in task_scope:
            # 检查任务是否已经完全完成
            task_fully_completed = utils.is_task_fully_completed(
                output_dir,
                task.task_identifier,
                agent_name,
                args.max_attempts,
                args.reasoning_mode,
                args.action_mode,
            )

            if task_fully_completed and not result_overwrite:
                print(
                    f"Task {task.task_identifier} is already fully completed. Skipping."
                )
                continue
            elif task_fully_completed and result_overwrite:
                print(
                    f"Task {task.task_identifier} is already fully completed. Overwriting due to --overwrite flag."
                )
                utils.clear_task_results(
                    output_dir,
                    task.task_identifier,
                    agent_name,
                    args.max_attempts,
                    args.reasoning_mode,
                    args.action_mode,
                )

            # 检查是否已经有成功的attempt，如果有则不需要添加更多attempts
            has_successful_attempt = False
            for attempt in range(1, args.max_attempts + 1):
                # 检查之前的attempts是否已经成功
                if check_attempt_success(
                    output_dir,
                    task.task_identifier,
                    agent_name,
                    attempt,
                    args.reasoning_mode,
                    args.action_mode,
                ):
                    print(
                        f"Task {task.task_identifier} already has a successful attempt ({attempt}). Skipping remaining attempts."
                    )
                    has_successful_attempt = True
                    break

            # 只在没有成功attempt的情况下，才添加所有attempts到工作队列
            if not has_successful_attempt:
                for attempt in range(1, args.max_attempts + 1):
                    work_queue.append(
                        {
                            "agent_name": agent_name,
                            "task": task,
                            "attempt": attempt,
                            "priority": task_scope.index(task) * args.max_attempts
                            + (attempt - 1),  # 同一任务的不同attempts可以并发执行
                        }
                    )

    # 按优先级排序工作队列（任务顺序优先，然后是attempt顺序）
    work_queue.sort(key=lambda x: x["priority"])

    print(f"Created work queue with {len(work_queue)} attempt executions")

    # 使用ThreadPoolExecutor进行并发执行
    max_workers = min(len(devices), len(work_queue))
    print(f"Using {max_workers} concurrent workers")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有工作任务
        future_to_work = {}
        device_index = 0

        for work_item in work_queue:
            # 循环分配设备
            device = devices[device_index % len(devices)]
            device_index += 1

            future = executor.submit(
                run_single_attempt,
                work_item["agent_name"],
                work_item["task"],
                work_item["attempt"],
                device,
            )
            future_to_work[future] = work_item

        # 等待所有任务完成并处理结果
        completed_count = 0
        for future in future_to_work:
            try:
                success = future.result()  # 获取执行结果
                work_item = future_to_work[future]
                completed_count += 1
                status = "SUCCESS" if success else "FAILED"
                print(
                    f"[{completed_count}/{len(work_queue)}] {status}: Task {work_item['task'].task_identifier}, attempt {work_item['attempt']}"
                )
            except Exception as e:
                work_item = future_to_work[future]
                print(
                    f"Error executing task {work_item['task'].task_identifier}, attempt {work_item['attempt']}: {e}"
                )

    print("=== Concurrent benchmark mode completed ===")


def run_parallel_by_task_groups():
    """
    按任务组动态并行执行：
    - 将任务按镜像关系分组（001-002, 003-004, etc.）
    - 使用任务队列，设备完成当前任务组后自动获取下一个
    - 确保镜像任务在同一设备上顺序执行
    - 实现真正的动态负载均衡
    """
    import threading
    import queue

    print("=== Parallel execution by task groups mode (Dynamic) ===")
    print(
        f"Available devices: {len(devices)}, Max attempts per task: {args.max_attempts}"
    )

    # 对每个agent执行
    for agent_name in agent_scope:
        print(f"\n>>> Processing agent: {agent_name} <<<")

        # 将任务按类型分组（传入设备数量以优化分配）
        task_groups = group_tasks_by_type(task_scope, num_devices=len(devices))
        print(f"Grouped {len(task_scope)} tasks into {len(task_groups)} task groups")

        # 打印任务组信息
        for i, group in enumerate(task_groups):
            task_ids = [t.task_identifier for t in group]
            print(f"Task group {i + 1}: {task_ids}")

        # 创建任务队列
        task_queue = queue.Queue()
        for task_group in task_groups:
            task_queue.put(task_group)

        print(f"Created task queue with {task_queue.qsize()} task groups")

        # 创建工作线程，每个设备一个线程
        threads = []
        for i, device in enumerate(devices):
            thread = threading.Thread(
                target=device_worker,
                args=(
                    device,
                    task_queue,
                    agent_name,
                    subprocess_list,
                    i + 1,
                    len(devices),
                ),
            )
            threads.append(thread)
            thread.start()
            print(f"Started worker thread {i + 1} for device {device['serial']}")

        # 等待所有线程完成
        for i, thread in enumerate(threads):
            thread.join()
            print(f"Worker thread {i + 1} completed")

        print(f"<<< Completed all task groups for agent {agent_name} >>>")


def device_worker(
    device, task_queue, agent_name, subprocess_list, worker_id, total_workers
):
    """
    设备工作线程：从任务队列中动态获取任务组并执行。

    Args:
        device: 设备信息
        task_queue: 任务队列（线程安全）
        agent_name: agent名称
        subprocess_list: 子进程列表
        worker_id: 工作线程编号
        total_workers: 总工作线程数
    """
    import queue

    device_serial = device["serial"]
    print(f"[Worker {worker_id}|{device_serial}] Worker started")

    completed_groups = 0

    while True:
        try:
            # 从队列获取任务组（非阻塞，超时1秒）
            task_group = task_queue.get(block=True, timeout=1)
        except queue.Empty:
            # 队列为空，退出
            print(
                f"[Worker {worker_id}|{device_serial}] No more tasks, shutting down (completed {completed_groups} groups)"
            )
            break

        try:
            # 执行任务组
            task_ids = [t.task_identifier for t in task_group]
            print(
                f"[Worker {worker_id}|{device_serial}] Starting task group: {task_ids}"
            )

            for task in task_group:
                print(
                    f"[Worker {worker_id}|{device_serial}] >>> Processing task {task.task_identifier} <<<"
                )

                # 使用单个设备列表来执行任务，确保所有attempts都在同一设备上
                single_device_list = [device]
                run_task_benchmark(
                    agent_name, task, subprocess_list, single_device_list
                )

                print(
                    f"[Worker {worker_id}|{device_serial}] <<< Completed task {task.task_identifier} >>>"
                )

            completed_groups += 1
            print(
                f"[Worker {worker_id}|{device_serial}] Finished task group {task_ids} ({completed_groups} total)"
            )

        except Exception as e:
            print(
                f"[Worker {worker_id}|{device_serial}] Error processing task group: {e}"
            )
            import traceback

            traceback.print_exc()
        finally:
            # 标记任务完成
            task_queue.task_done()

    print(
        f"[Worker {worker_id}|{device_serial}] Worker finished (total completed: {completed_groups})"
    )


def run_eval_only_mode():
    """
    仅评估模式：批量评估所有任务
    """
    print("Running in eval-only mode...")
    eval_tasks = utils.collect_evaluation_tasks(
        output_dir,
        agent_scope,
        task_scope,
        args.max_attempts,
        args.reasoning_mode,
        args.action_mode,
        result_overwrite,
    )

    if not eval_tasks:
        print("No evaluation tasks found.")
        return

    eval_futures = []
    print(f"Submitting {len(eval_tasks)} evaluation tasks...")

    for eval_task in eval_tasks:
        future = eval_executor.submit(
            utils.execute_evaluation,
            eval_task["task_identifier"],
            output_dir,
            args.mode,
            eval_task["agent_name"],
            eval_task["attempt"],
            args.reasoning_mode,
            args.action_mode,
            eval_task["attempt_dir"],
            result_overwrite,
        )
        eval_futures.append(future)

    # 处理评估结果
    utils.process_evaluation_results(
        output_dir, eval_tasks, eval_futures, args.reasoning_mode, args.action_mode
    )
    print_realtime_progress("Evaluation Batch Done")


# 主执行逻辑
# Initialize timing tracking
initialize_timing(output_dir)
print_realtime_progress("Startup")

if args.mode == "eval":
    run_eval_only_mode()
else:
    # 执行任务（full或exec模式）
    print("=== Starting benchmark execution mode ===")

    print(
        f"Available devices: {len(devices)}, Max attempts per task: {args.max_attempts}"
    )

    # 智能选择执行策略
    if len(devices) > 1 and len(task_scope) > 1 and not args.no_concurrent:
        # 多设备并发模式：按任务组分配设备，充分利用所有设备
        print(
            f"Using parallel execution mode with {len(devices)} devices for task groups"
        )
        run_parallel_by_task_groups()
    else:
        # 单任务串行模式：适用于单设备或单任务的情况
        print("Using sequential benchmark mode")
        if len(devices) < args.max_attempts:
            print(
                f"Warning: Only {len(devices)} devices available for {args.max_attempts} attempts. Devices will be reused."
            )

        # 按任务顺序逐个执行，每个任务的所有attempts都完成后再执行下一个任务
        for agent_name in agent_scope:
            for task in task_scope:
                print(
                    f"\n>>> Processing task {task.task_identifier} with agent {agent_name} <<<"
                )
                run_task_benchmark(agent_name, task, subprocess_list, devices)

# 清理工作
if args.setup_avd or args.setup_emulator:
    utils.terminate_emulator([device["serial"] for device in devices])

if args.mode != "eval":
    print("All execution completed.")

# 等待所有子进程完成
for process in subprocess_list:
    process.wait()

# 关闭评估任务执行器
eval_executor.shutdown(wait=True)
print("All tasks completed.")

# 打印最终指标总结
print("\n" + "=" * 100)
print("[*] FINAL METRICS SUMMARY")
print("=" * 100)

# 使用新的实时指标模块计算并打印最终指标
final_metrics = calculate_and_save_metrics(
    output_dir=output_dir,
    max_attempts=args.max_attempts,
    trigger="Final Summary",
    print_summary=True,
    save_to_file=True,
)

if final_metrics:
    print("\nMetrics have been saved to:")
    print(f"  - {output_dir}/metrics_summary.json")
    print(f"  - {output_dir}/metrics_summary.csv")
    print(f"  - {output_dir}/metrics_history.jsonl")

    # 保存 MemGUI-Bench Leaderboard 格式的结果
    agent_name = config.get("AGENT_NAME", "Unknown")

    leaderboard_path = save_leaderboard_result(
        output_dir=output_dir,
        metrics=final_metrics,
        agent_name=agent_name,
    )
    print(f"  - {leaderboard_path} (Leaderboard format - fill in metadata before submission)")
else:
    print("\nWarning: No metrics could be calculated. Check results.csv exists.")

print(f"\nResults CSV: {output_dir}/results.csv")
