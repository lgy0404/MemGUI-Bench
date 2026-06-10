import pandas as pd
from . import agents
import subprocess
import os
import shutil
import json
import time
import re
import shlex
import sys
from filelock import FileLock
from functools import wraps
from datetime import datetime


def get_apk(device_serial: str, package_name: str, local_apk_path: str):
    adb_command = f"adb -s {device_serial} shell pm path {package_name}"
    apk_path = execute_adb(adb_command)
    if apk_path == "ERROR":
        return "ERROR"
    apk_path = apk_path.split("package:")[1].strip()
    adb_command = f"adb -s {device_serial} pull {apk_path} {local_apk_path}"
    return execute_adb(adb_command)


def get_agent(agent_name):
    try:
        return getattr(agents, agent_name)
    except AttributeError:
        raise Exception(f"Required agent <{agent_name}> not implemented.")


def get_agent_config(config, agent_name):
    for agent in config["AGENTS"]:
        if agent["NAME"] == agent_name:
            return agent
    raise Exception("INVALID agent_name")


def execute_adb(adb_command, verbose=True):
    try:
        result = subprocess.run(adb_command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        if verbose:
            print(f"Command execution failed: {adb_command}")
            print(result.stderr)
        return "ERROR"
    except UnicodeDecodeError:
        # Handle non-UTF-8 output by using binary mode and manual decoding
        try:
            result = subprocess.run(adb_command, shell=True, capture_output=True)
            if result.returncode == 0:
                return result.stdout.decode("utf-8", errors="replace").strip()
            if verbose:
                print(f"Command execution failed: {adb_command}")
                print(result.stderr.decode("utf-8", errors="replace"))
            return "ERROR"
        except Exception as e:
            if verbose:
                print(f"Command execution failed with exception: {adb_command}")
                print(f"Exception: {e}")
            return "ERROR"


def get_all_devices():
    adb_command = "adb devices"
    device_list = []
    result = execute_adb(adb_command)
    if result != "ERROR":
        devices = result.split("\n")[1:]
        for d in devices:
            device_list.append(d.split()[0])

    return device_list


def setup_devices():
    devices = get_all_devices()
    print(f"{len(devices)} device(s) found: {devices}")
    preferred_device = os.environ.get("MEMGUI_DEVICE_SERIAL")
    if preferred_device:
        if preferred_device not in devices:
            print(f"Preferred device {preferred_device} not found.")
            exit(1)
        return [
            {"serial": preferred_device, "console_port": None, "grpc_port": None}
        ]
    if len(devices) == 0:
        exit(1)
    elif len(devices) > 1:
        ans = input("Are you sure to run using all devices? (y/n)")
        if ans.strip().lower() != "y":
            exit(1)
    return [
        {"serial": serial, "console_port": None, "grpc_port": None}
        for serial in devices
    ]


def setup_avd(
    avd_home, source_avd_home, source_avd_name, num_of_copies, target_sdk_path
):
    from .utils_clone_avd import clone_avd

    for idx in range(num_of_copies):
        clone_avd(
            src_avd_dir=os.path.join(source_avd_home, source_avd_name + ".avd"),
            src_ini_file=os.path.join(source_avd_home, source_avd_name + ".ini"),
            src_avd_name=source_avd_name,
            tar_avd_name=f"{source_avd_name}_{idx}",
            src_android_avd_home=r"C:\Users\User\.android\avd",
            tar_android_avd_home=avd_home,
            src_sdk=r"C:\Users\User\AppData\Local\Android\Sdk",
            tar_sdk=target_sdk_path,
            target_linux=os.name == "posix",
        )


def parse_adb_devices(res) -> dict:
    devices = {}
    for line in res.split("\n")[1:]:
        serial, status = line.split("\t")
        devices[serial] = status
    return devices


def setup_emulator(emulator_exe, source_avd_name, num_of_emulators):
    sdk_path = os.path.dirname(os.path.dirname(emulator_exe))
    adb_path = os.path.join(sdk_path, "platform-tools")
    os.environ["PATH"] = f"{adb_path}{os.pathsep}{os.environ['PATH']}"
    devices = [
        {
            "serial": f"emulator-{5554 + (idx * 2)}",
            "console_port": 5554 + (idx * 2),
            "grpc_port": 8554 + (idx * 2),
        }
        for idx in range(num_of_emulators)
    ]
    devices_serial = [device["serial"] for device in devices]
    ready_devices = []
    for idx, device in enumerate(devices):
        command = [
            emulator_exe,
            "-avd",
            f"{source_avd_name}_{idx}",
            "-no-snapshot-save",
            "-no-window",
            "-no-audio",
            "-port",
            str(device["console_port"]),
            "-grpc",
            str(device["grpc_port"]),
        ]
        # add “no-window” to the command if need to run in headless mode
        http_proxy = os.environ.get("HTTP_PROXY")
        if http_proxy:
            command.extend(["-http-proxy", http_proxy])
        subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.DEVNULL,  # to silence emulator output
            # keep any error output
        )
    adb_command = "adb devices"
    while True:
        result = execute_adb(adb_command)
        if result == "ERROR":
            raise Exception("Error in executing ADB command")
        else:
            launched_devices = [
                serial
                for serial, status in parse_adb_devices(result).items()
                if status == "device" and serial in devices_serial
            ]
            print(
                f"{len(launched_devices)}/{num_of_emulators} device(s) launched; {len(ready_devices)}/{num_of_emulators} device(s) ready"
            )
            if len(launched_devices) == num_of_emulators:
                break
            else:
                time.sleep(1)
    while True:
        for serial in launched_devices:
            if serial in ready_devices:
                continue
            result = execute_adb(f"adb -s {serial} shell getprop sys.boot_completed")
            if result == "1":
                ready_devices.append(serial)
        print(
            f"{len(launched_devices)}/{num_of_emulators} device(s) launched; {len(ready_devices)}/{num_of_emulators} device(s) ready"
        )
        if len(ready_devices) == num_of_emulators:
            break
        else:
            time.sleep(1)

    # Wait for emulators to fully stabilize after boot
    print("All emulators are ready. Waiting 30 seconds for full stabilization...")
    time.sleep(30)
    print("Stabilization complete. Proceeding with task execution.")

    return devices


def terminate_emulator(serial_list):
    for serial in serial_list:
        try:
            result = execute_adb(f"adb -s {serial} emu kill", verbose=False)
            if result != "ERROR":
                print(f"Successfully terminated emulator: {serial}")
            else:
                print(f"Failed to terminate emulator: {serial}")
        except Exception as e:
            print(f"Exception while terminating emulator {serial}: {e}")
            continue


def check_device_connectivity(device_serial):
    """
    检查设备是否在线并可访问
    :param device_serial: 设备序列号
    :return: True if device is online and accessible, False otherwise
    """
    try:
        # 检查设备是否在adb devices列表中
        result = execute_adb("adb devices", verbose=False)
        if result == "ERROR":
            return False

        # 解析设备状态
        devices = parse_adb_devices(result)
        if device_serial not in devices:
            return False

        if devices[device_serial] != "device":
            return False

        # 进一步检查设备是否响应
        response = execute_adb(
            f"adb -s {device_serial} shell echo 'alive'", verbose=False
        )
        return response == "alive"
    except Exception:
        return False


def restart_emulator(device_info, emulator_exe, source_avd_name):
    """
    重启单个emulator
    :param device_info: 设备信息字典，包含serial, console_port, grpc_port
    :param emulator_exe: emulator可执行文件路径
    :param source_avd_name: AVD名称
    :return: True if restart successful, False otherwise
    """
    try:
        device_serial = device_info["serial"]
        console_port = device_info["console_port"]
        grpc_port = device_info["grpc_port"]

        print(f"Restarting emulator {device_serial}...")

        # 1. 先尝试杀死旧的emulator进程
        execute_adb(f"adb -s {device_serial} emu kill", verbose=False)
        time.sleep(2)

        # 2. 提取设备索引
        if "emulator-" in device_serial:
            port_num = int(device_serial.split("-")[1])
            device_idx = (port_num - 5554) // 2
        else:
            return False

        # 3. 启动新的emulator
        command = [
            emulator_exe,
            "-avd",
            f"{source_avd_name}_{device_idx}",
            "-no-snapshot-save",
            "-no-window",
            "-no-audio",
            "-port",
            str(console_port),
            "-grpc",
            str(grpc_port),
        ]

        # 添加HTTP代理设置（如果有）
        http_proxy = os.environ.get("HTTP_PROXY")
        if http_proxy:
            command.extend(["-http-proxy", http_proxy])

        # 启动emulator
        subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print(f"Emulator {device_serial} started, waiting for it to be ready...")

        # 4. 等待emulator启动完成
        max_wait_time = 120  # 最大等待120秒
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            # 检查设备是否已启动
            result = execute_adb("adb devices", verbose=False)
            if result != "ERROR":
                devices = parse_adb_devices(result)
                if device_serial in devices and devices[device_serial] == "device":
                    # 检查设备是否完全启动
                    boot_result = execute_adb(
                        f"adb -s {device_serial} shell getprop sys.boot_completed",
                        verbose=False,
                    )
                    if boot_result == "1":
                        print(
                            f"Emulator {device_serial} is ready! Waiting 30 seconds for full stabilization..."
                        )
                        time.sleep(30)
                        print(f"Emulator {device_serial} stabilization complete.")
                        return True
            time.sleep(3)

        print(f"Timeout waiting for emulator {device_serial} to be ready")
        return False

    except Exception as e:
        print(f"Error restarting emulator {device_info}: {e}")
        return False


def check_and_restart_device_if_needed(device_info, emulator_exe, source_avd_name):
    """
    检查设备状态，如果掉线则重启
    :param device_info: 设备信息字典
    :param emulator_exe: emulator可执行文件路径
    :param source_avd_name: AVD名称
    :return: True if device is ready, False if restart failed
    """
    device_serial = device_info["serial"]

    # 检查设备连接性
    if check_device_connectivity(device_serial):
        return True

    print(f"Device {device_serial} is offline, attempting to restart...")

    # 尝试重启设备
    if restart_emulator(device_info, emulator_exe, source_avd_name):
        return True

    print(f"Failed to restart device {device_serial}")
    return False


def setup_app_activity(device_serial: str, adb_app: str, adb_home_page: str) -> bool:
    """Open the home page of the target app. Go to home-screen if failed or no info is given.

    Parameters:
    - device_serial (str): The android device serial number.
    - adb_app (str): The application package name.
    - adb_home_page (str): The activity class name.

    Returns:
    - bool: Whether the home page is successfully opened.
    """
    # Close app
    close_app_activity(device_serial, adb_app)

    # Start app
    launched = False
    if adb_app and adb_home_page:
        output = execute_adb(
            f"adb -s {device_serial} shell am start -n {adb_app}/{adb_home_page}",
            verbose=False,
        )
        if output != "ERROR":
            launched = True
    if not launched and adb_app:
        output = execute_adb(
            f"adb -s {device_serial} shell monkey -p {adb_app} -c android.intent.category.LAUNCHER 1"
        )
        if output != "ERROR":
            launched = True
    if launched:
        max_retry = 30
        trial = 0
        while trial < max_retry:
            windows = execute_adb(
                f'adb -s {device_serial} shell "dumpsys window | grep -E mCurrentFocus"',
                verbose=False,
            )
            if windows == "ERROR":
                break
            m = re.search(
                r"mCurrentFocus=Window{.*\s+(?P<package>[^\s]+)/(?P<activity>[^\s]+)\}",
                windows,
            )
            if m and m.group("package") == adb_app:
                break
            else:
                time.sleep(1)
                trial += 1
        time.sleep(10)  # For loading app content
        return True
    else:
        execute_adb(f"adb -s {device_serial} shell input keyevent KEYCODE_HOME")
        print(
            f"10 seconds are allowed to start the app `{adb_app}/{adb_home_page}` on {device_serial} manually:"
        )
        time.sleep(10)
        return False


def close_app_activity(
    device_serial: str, adb_app: str = None, kill_every_task: bool = True
) -> bool:
    """Kill every app.

    Parameters:
    - device_serial (str): The android device serial number.
    - adb_app (str): The application package name.
    - kill_every_task (bool): Whether to kill all running apps.

    Returns:
    - bool: Whether the app is successfully closed.
    """
    if kill_every_task:
        execute_adb(
            f'''adb -s {device_serial} shell "dumpsys activity | grep topActivity | sed -n 's/.*{{\\([^\\/]*\\)\\/.*/\\1/p' | while read -r package; do if [ -n \\"\\$package\\" ]; then am force-stop \\"\\$package\\"; fi; done"'''
        )
    # Kill specific app
    if adb_app:
        output = execute_adb(f"adb -s {device_serial} shell am force-stop {adb_app}")
        if output != "ERROR":
            time.sleep(5)
            return True
    return False


def set_adb_keyboard(device_serial):
    execute_adb(
        f"adb -s {device_serial} shell ime enable com.android.adbkeyboard/.AdbIME"
    )
    execute_adb(f"adb -s {device_serial} shell ime set com.android.adbkeyboard/.AdbIME")


def set_default_keyboard(device_serial, package):
    execute_adb(f"adb -s {device_serial} shell ime set {package}")


def setup_output_directory(
    results_dir: str, session_id: str, overwrite_session: bool
) -> str:
    output_dir = os.path.join(results_dir, f"session-{session_id}")

    if os.path.exists(output_dir):
        if overwrite_session:
            # Directory exists, prompt the user
            response = (
                input(
                    f"The results session <{session_id}> already exists. Do you want to erase its contents and restart the session? (y/n): "
                )
                .strip()
                .lower()
            )
            if response in ["yes", "y"]:
                # Erase the contents
                for item in os.listdir(output_dir):
                    item_path = os.path.join(output_dir, item)
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
            else:
                pass
        else:
            pass
    else:
        # Create the directory
        os.makedirs(output_dir)
    return output_dir


def get_results_csv_path(output_dir: str) -> str:
    return os.path.join(output_dir, "results.csv")


def get_results_df(output_dir: str) -> pd.DataFrame:
    """Safely reads the results CSV into a DataFrame."""
    csv_path = get_results_csv_path(output_dir)
    return pd.read_csv(csv_path)


def get_col_name_from_template(
    template_name: str,
    agent_name: str = None,
    eval_name: str = None,
    sub_eval_name: str = None,
    attempt_num: int = None,
):
    """Generates a column name based on a template."""
    parts = []
    if agent_name:
        parts.append(agent_name)
    if eval_name:
        parts.append(eval_name)
    if sub_eval_name:
        parts.append(sub_eval_name)
    if attempt_num:
        parts.append(f"attempt_{attempt_num}")

    # Only append the main metric name (template_name) if it's not empty
    if template_name:
        parts.append(template_name)
    return "_".join(parts)


def get_exec_json_path(
    output_dir: str, task_id: str, agent_name: str, content: str
) -> str:
    return os.path.join(output_dir, task_id, agent_name, f"{content}.json")


def with_filelock():
    """Decorator to add a simple file lock context to the wrapped function using the 'output_dir'
    argument.

    Returns:
    - A decorated function with a file lock.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract the output_dir argument from function arguments
            output_dir = kwargs.get("output_dir") or next(
                (
                    arg
                    for arg_name, arg in zip(func.__code__.co_varnames, args)
                    if arg_name == "output_dir"
                ),
                None,
            )

            if not output_dir:
                raise ValueError("Lock path argument output_dir is required.")

            csv_path = get_results_csv_path(output_dir)
            lock = FileLock(csv_path + ".lock")

            start_time = datetime.now()
            with lock:
                print("Time taken to get lock:", datetime.now() - start_time)
                result = func(*args, **kwargs)
                return result

        return wrapper

    return decorator


def try_save_csv(
    dataframe: pd.DataFrame, path: str, max_retry: int = 5, retry_interval: int = 5
) -> bool:
    counter = 0
    while True:
        try:
            dataframe.to_csv(path, encoding="utf-8", index=False)
        except Exception as err:
            print("Failed to save to ", path)
            print(str(err))
            if counter < max_retry:
                counter += 1
                print(f"Retry in {retry_interval} seconds; {counter}/{max_retry}")
                time.sleep(retry_interval)
                continue
            else:
                return False
        return True


def _try_load_json(x):
    try:
        return json.loads(x.replace("'", '"'))
    except (json.JSONDecodeError, TypeError):
        return {}


@with_filelock()
def setup_results_csv(
    output_dir: str,
    dataset_path: str,
    agent_list: list[str],
    max_attempts: int,
    reasoning_mode: str,
    action_mode: str,
) -> pd.DataFrame:
    """Setup the CSV file for storing results.

    This function will create a new results.csv file or load an existing one.
    It adds necessary columns for each agent and each attempt.

    Parameters:
    - output_dir (str): The directory where the results are stored.
    - dataset_path (str): The path to the original dataset CSV.
    - agent_list (list[str]): A list of agent names.
    - max_attempts (int): Maximum number of attempts for each task.

    Returns:
    - pd.DataFrame: The initialized or loaded DataFrame.
    """
    csv_path = get_results_csv_path(output_dir)
    if os.path.exists(csv_path):
        print("Loaded existing results.csv")
        for encoding in ["utf-8", "gbk", "gb18030", "utf-8-sig", "latin1"]:
            try:
                return pd.read_csv(csv_path, encoding=encoding)
            except UnicodeDecodeError:
                continue
    else:
        print("Created results.csv")
        results_df = pd.read_csv(dataset_path, keep_default_na=False)
        results_df.set_index("task_identifier", inplace=True)

        for agent_name in agent_list:
            # Add success tracking columns
            results_df[f"{agent_name}_successful_attempts"] = (
                "[]"  # Array of successful attempt numbers
            )
            results_df[f"{agent_name}_success_count"] = 0  # Total number of successes

            for i in range(1, max_attempts + 1):
                # Columns for each attempt
                exec_col_prefix = get_col_name_from_template(
                    "", agent_name=agent_name, attempt_num=i
                )
                eval_col_prefix = get_col_name_from_template(
                    "",
                    agent_name=agent_name,
                    eval_name=reasoning_mode,
                    sub_eval_name=action_mode,
                    attempt_num=i,
                )

                results_df[f"{exec_col_prefix}_completion"] = "N"
                results_df[f"{exec_col_prefix}_device"] = "N"
                results_df[f"{exec_col_prefix}_exit_code"] = -1
                results_df[f"{exec_col_prefix}_total_steps"] = 0
                results_df[f"{exec_col_prefix}_total_token_cost"] = 0.0
                results_df[f"{exec_col_prefix}_total_time"] = 0.0
                results_df[f"{exec_col_prefix}_finish_signal"] = 0
                results_df[f"{exec_col_prefix}_step_ratio"] = 0.0
                results_df[f"{exec_col_prefix}_elapsed_time_initial"] = 0.0
                results_df[f"{exec_col_prefix}_elapsed_time_exec"] = 0.0
                results_df[f"{exec_col_prefix}_avg_prompt_tokens"] = 0
                results_df[f"{exec_col_prefix}_avg_completion_tokens"] = 0
                results_df[f"{exec_col_prefix}_exec_error"] = "N"

                results_df[f"{eval_col_prefix}_evaluation"] = "N"
                results_df[f"{eval_col_prefix}_details"] = "{}"
                results_df[f"{eval_col_prefix}_evaluation_method"] = ""

                # 总计token使用情况
                results_df[f"{eval_col_prefix}_eval_prompt_tokens"] = 0
                results_df[f"{eval_col_prefix}_eval_completion_tokens"] = 0
                results_df[f"{eval_col_prefix}_eval_total_tokens"] = 0
                results_df[f"{eval_col_prefix}_eval_api_cost"] = 0.0
                results_df[f"{eval_col_prefix}_model_provider"] = ""
                results_df[f"{eval_col_prefix}_model_name"] = ""

                # 步骤描述生成的token使用情况
                results_df[f"{eval_col_prefix}_step_desc_prompt_tokens"] = 0
                results_df[f"{eval_col_prefix}_step_desc_completion_tokens"] = 0
                results_df[f"{eval_col_prefix}_step_desc_total_tokens"] = 0
                results_df[f"{eval_col_prefix}_step_desc_api_cost"] = 0.0
                results_df[f"{eval_col_prefix}_step_desc_model_name"] = ""
                results_df[f"{eval_col_prefix}_step_desc_model_provider"] = ""

                # 最终决策的token使用情况
                results_df[f"{eval_col_prefix}_final_decision_prompt_tokens"] = 0
                results_df[f"{eval_col_prefix}_final_decision_completion_tokens"] = 0
                results_df[f"{eval_col_prefix}_final_decision_total_tokens"] = 0
                results_df[f"{eval_col_prefix}_final_decision_api_cost"] = 0.0
                results_df[f"{eval_col_prefix}_final_decision_model_name"] = ""
                results_df[f"{eval_col_prefix}_final_decision_model_provider"] = ""

                # BadCase 分析结果
                results_df[f"{eval_col_prefix}_badcase_category"] = ""
                results_df[f"{eval_col_prefix}_badcase_confidence"] = 0.0
                results_df[f"{eval_col_prefix}_badcase_analysis_reason"] = ""
                results_df[f"{eval_col_prefix}_badcase_key_failure_point"] = ""
                results_df[f"{eval_col_prefix}_badcase_evidence"] = ""
                results_df[f"{eval_col_prefix}_badcase_suggested_improvement"] = ""

                # Self-reflection results
                results_df[f"{exec_col_prefix}_self_reflection_judgment"] = ""
                results_df[f"{exec_col_prefix}_self_reflection_prompt_tokens"] = 0
                results_df[f"{exec_col_prefix}_self_reflection_completion_tokens"] = 0
                results_df[f"{exec_col_prefix}_self_reflection_total_tokens"] = 0
                results_df[f"{exec_col_prefix}_self_reflection_api_cost"] = 0.0

        results_df.reset_index(inplace=True)
        try_save_csv(results_df, csv_path)
        return results_df


@with_filelock()
def save_result__completed_execution(
    output_dir: str,
    task_id: str,
    agent_name: str,
    task_completed: bool,
    exit_code: int,
    device: str,
    attempt_num: int,
) -> pd.DataFrame:
    """Save the task execution result to the CSV.

    This function is decorated with a file lock to ensure thread/process safety.
    """
    df = pd.read_csv(get_results_csv_path(output_dir))
    df.set_index("task_identifier", inplace=True)
    row_index = df.index.get_loc(task_id)

    prefix = get_col_name_from_template(
        "", agent_name=agent_name, attempt_num=attempt_num
    )
    df.loc[task_id, f"{prefix}_completion"] = "Y" if task_completed else "N"
    df.loc[task_id, f"{prefix}_exit_code"] = exit_code
    df.loc[task_id, f"{prefix}_device"] = device

    # Also log execution summary if exists
    log_path = os.path.join(
        output_dir, task_id, agent_name, f"attempt_{attempt_num}", "log.json"
    )
    if os.path.exists(log_path):
        with open(log_path) as f:
            log_data = json.load(f)
            summary = log_data[-1]  # The summary is the last element
            df.loc[task_id, f"{prefix}_total_steps"] = summary.get("total_steps", 0)
            df.loc[task_id, f"{prefix}_finish_signal"] = summary.get("finish_signal", 0)
            df.loc[task_id, f"{prefix}_elapsed_time_initial"] = summary.get(
                "elapsed_time_initial", 0.0
            )
            df.loc[task_id, f"{prefix}_elapsed_time_exec"] = summary.get(
                "elapsed_time_exec", 0.0
            )

            # Calculate and record additional metrics
            total_prompt_tokens = summary.get("total_prompt_tokens", 0)
            total_completion_tokens = summary.get("total_completion_tokens", 0)
            total_steps = summary.get("total_steps", 0)
            elapsed_time_total = summary.get("elapsed_time_initial", 0.0) + summary.get(
                "elapsed_time_exec", 0.0
            )

            # Record token-related metrics
            df.loc[task_id, f"{prefix}_avg_prompt_tokens"] = (
                total_prompt_tokens // total_steps if total_steps > 0 else 0
            )
            df.loc[task_id, f"{prefix}_avg_completion_tokens"] = (
                total_completion_tokens // total_steps if total_steps > 0 else 0
            )

            # Calculate total token cost (basic estimation, adjust based on actual pricing)
            # Using rough estimates: $0.01 per 1K prompt tokens, $0.03 per 1K completion tokens
            prompt_cost = (total_prompt_tokens / 1000) * 0.01
            completion_cost = (total_completion_tokens / 1000) * 0.03
            df.loc[task_id, f"{prefix}_total_token_cost"] = (
                prompt_cost + completion_cost
            )

            # Record total time
            df.loc[task_id, f"{prefix}_total_time"] = elapsed_time_total

            # Calculate step ratio (ratio of actual steps to some expected maximum)
            # This could be based on golden_steps from the dataset if available
            # For now, using a simple completion ratio based on finish_signal
            finish_signal = summary.get("finish_signal", 0)
            if finish_signal == 1:  # Task completed successfully
                df.loc[task_id, f"{prefix}_step_ratio"] = 1.0
            else:
                # Calculate based on actual steps vs some reasonable maximum
                max_expected_steps = 50  # Reasonable maximum for most tasks
                df.loc[task_id, f"{prefix}_step_ratio"] = min(
                    total_steps / max_expected_steps, 1.0
                )

    df.reset_index(inplace=True)
    try_save_csv(df, get_results_csv_path(output_dir))
    return df


@with_filelock()
def save_result__completed_evaluation(
    output_dir: str,
    task_id: str,
    agent_name: str,
    success: int,
    evaluation_detail: dict,
    reasoning_mode: str,
    action_mode: str,
    attempt_num: int,
    evaluation_method: str = "",
    # 移除总计token使用参数，只保留分类的token统计
    # eval_prompt_tokens: int = 0,
    # eval_completion_tokens: int = 0,
    # eval_total_tokens: int = 0,
    # eval_api_cost: float = 0.0,
    # model_provider: str = "",
    # model_name: str = "",
    # 步骤描述生成的token使用
    step_desc_prompt_tokens: int = 0,
    step_desc_completion_tokens: int = 0,
    step_desc_total_tokens: int = 0,
    step_desc_api_cost: float = 0.0,
    step_desc_model_name: str = "",
    step_desc_model_provider: str = "",
    # 最终决策的token使用
    final_decision_prompt_tokens: int = 0,
    final_decision_completion_tokens: int = 0,
    final_decision_total_tokens: int = 0,
    final_decision_api_cost: float = 0.0,
    final_decision_model_name: str = "",
    final_decision_model_provider: str = "",
    # 失败步骤追踪
    failure_step: int = None,
) -> pd.DataFrame:
    """Save the task evaluation result to the CSV.

    This function is decorated with a file lock to ensure thread/process safety.
    It converts numeric success codes (1, 0, -1) to string representations ('S', 'F', 'E').
    """
    df = pd.read_csv(get_results_csv_path(output_dir))
    df.set_index("task_identifier", inplace=True)

    prefix = get_col_name_from_template(
        "",
        agent_name=agent_name,
        eval_name=reasoning_mode,
        sub_eval_name=action_mode,
        attempt_num=attempt_num,
    )

    result_map = {1: "S", 0: "F", -1: "E"}
    evaluation_result = result_map.get(success, "E")  # Default to Error

    df.loc[task_id, f"{prefix}_evaluation"] = evaluation_result
    df.loc[task_id, f"{prefix}_details"] = str(evaluation_detail)
    df.loc[task_id, f"{prefix}_evaluation_method"] = evaluation_method

    # 移除总计token使用情况的存储，只保留分类的token统计
    # df.loc[task_id, f"{prefix}_eval_prompt_tokens"] = eval_prompt_tokens
    # df.loc[task_id, f"{prefix}_eval_completion_tokens"] = eval_completion_tokens
    # df.loc[task_id, f"{prefix}_eval_total_tokens"] = eval_total_tokens
    # df.loc[task_id, f"{prefix}_eval_api_cost"] = eval_api_cost
    # df.loc[task_id, f"{prefix}_model_provider"] = model_provider
    # df.loc[task_id, f"{prefix}_model_name"] = model_name

    # 步骤描述生成的token使用情况
    df.loc[task_id, f"{prefix}_step_desc_prompt_tokens"] = step_desc_prompt_tokens
    df.loc[task_id, f"{prefix}_step_desc_completion_tokens"] = (
        step_desc_completion_tokens
    )
    df.loc[task_id, f"{prefix}_step_desc_total_tokens"] = step_desc_total_tokens
    df.loc[task_id, f"{prefix}_step_desc_api_cost"] = step_desc_api_cost
    df.loc[task_id, f"{prefix}_step_desc_model_name"] = step_desc_model_name
    df.loc[task_id, f"{prefix}_step_desc_model_provider"] = step_desc_model_provider

    # 最终决策的token使用情况
    df.loc[task_id, f"{prefix}_final_decision_prompt_tokens"] = (
        final_decision_prompt_tokens
    )
    df.loc[task_id, f"{prefix}_final_decision_completion_tokens"] = (
        final_decision_completion_tokens
    )
    df.loc[task_id, f"{prefix}_final_decision_total_tokens"] = (
        final_decision_total_tokens
    )
    df.loc[task_id, f"{prefix}_final_decision_api_cost"] = final_decision_api_cost
    df.loc[task_id, f"{prefix}_final_decision_model_name"] = final_decision_model_name
    df.loc[task_id, f"{prefix}_final_decision_model_provider"] = (
        final_decision_model_provider
    )

    # 失败步骤追踪
    df.loc[task_id, f"{prefix}_failure_step"] = (
        failure_step if failure_step is not None else ""
    )

    df.reset_index(inplace=True)
    try_save_csv(df, get_results_csv_path(output_dir))
    return df


@with_filelock()
def save_badcase_result(
    output_dir: str,  # Changed from result_dir to match with_filelock() expectation
    task_identifier: str,
    agent: str,
    attempt_num: int,
    reasoning_mode: str,
    action_mode: str,
    badcase_category: str,
    badcase_confidence: float,
    badcase_analysis_reason: str,
    badcase_key_failure_point: str,
    badcase_evidence: str,
    badcase_suggested_improvement: str,
) -> pd.DataFrame:
    """
    Save BadCase analysis result to CSV.

    Args:
        output_dir: Results directory (renamed from result_dir for filelock compatibility)
        task_identifier: Task ID
        agent: Agent name
        attempt_num: Attempt number
        reasoning_mode: Reasoning mode
        action_mode: Action mode
        badcase_category: BadCase category classification
        badcase_confidence: Confidence score (0.0-1.0)
        badcase_analysis_reason: Detailed analysis reason
        badcase_key_failure_point: Key failure point description
        badcase_evidence: Supporting evidence
        badcase_suggested_improvement: Suggested improvement

    Returns:
        Updated DataFrame
    """
    csv_path = get_results_csv_path(output_dir)
    df = pd.read_csv(csv_path)
    df.set_index("task_identifier", inplace=True)

    prefix = get_col_name_from_template(
        "",
        agent_name=agent,
        eval_name=reasoning_mode,
        sub_eval_name=action_mode,
        attempt_num=attempt_num,
    )

    # Save BadCase analysis fields
    df.loc[task_identifier, f"{prefix}_badcase_category"] = badcase_category
    df.loc[task_identifier, f"{prefix}_badcase_confidence"] = badcase_confidence
    df.loc[task_identifier, f"{prefix}_badcase_analysis_reason"] = (
        badcase_analysis_reason
    )
    df.loc[task_identifier, f"{prefix}_badcase_key_failure_point"] = (
        badcase_key_failure_point
    )
    df.loc[task_identifier, f"{prefix}_badcase_evidence"] = badcase_evidence
    df.loc[task_identifier, f"{prefix}_badcase_suggested_improvement"] = (
        badcase_suggested_improvement
    )

    df.reset_index(inplace=True)
    try_save_csv(df, csv_path)
    return df


@with_filelock()
def save_irr_result(
    output_dir: str,  # Changed from result_dir to match with_filelock() expectation
    task_identifier: str,
    agent: str,
    attempt_num: int,
    reasoning_mode: str,
    action_mode: str,
    irr_percentage,
    irr_total_units,
    irr_correct_units,
    irr_reason: str,
    irr_method: str,
) -> pd.DataFrame:
    """Save the IRR (Information Retention Rate) evaluation result to the CSV.

    Args:
        output_dir: Root results directory (renamed from result_dir for filelock compatibility)
        task_identifier: Task ID
        agent: Agent name
        attempt_num: Attempt number
        reasoning_mode: Reasoning mode
        action_mode: Action mode
        irr_percentage: IRR percentage (0-100 or None)
        irr_total_units: Total information units required
        irr_correct_units: Correctly used information units
        irr_reason: Analysis reason
        irr_method: Evaluation method used

    Returns:
        Updated DataFrame
    """
    df = pd.read_csv(get_results_csv_path(output_dir))
    df.set_index("task_identifier", inplace=True)

    prefix = get_col_name_from_template(
        "",
        agent_name=agent,
        eval_name=reasoning_mode,
        sub_eval_name=action_mode,
        attempt_num=attempt_num,
    )

    # Save IRR results to CSV
    df.loc[task_identifier, f"{prefix}_irr_percentage"] = (
        irr_percentage if irr_percentage is not None else ""
    )
    df.loc[task_identifier, f"{prefix}_irr_total_units"] = str(irr_total_units)
    df.loc[task_identifier, f"{prefix}_irr_correct_units"] = str(irr_correct_units)
    df.loc[task_identifier, f"{prefix}_irr_reason"] = (
        irr_reason[:500] if irr_reason else ""
    )  # Truncate long reasons
    df.loc[task_identifier, f"{prefix}_irr_method"] = irr_method

    df.reset_index(inplace=True)
    try_save_csv(df, get_results_csv_path(output_dir))  # Use output_dir

    return df


@with_filelock()
def update_success_tracking(
    output_dir: str, task_id: str, agent_name: str, attempt_num: int
) -> None:
    """Updates the success tracking columns for a given task and agent."""
    df = pd.read_csv(get_results_csv_path(output_dir))
    df.set_index("task_identifier", inplace=True)

    successful_attempts_col = f"{agent_name}_successful_attempts"
    success_count_col = f"{agent_name}_success_count"

    # Get current successful attempts list
    current_attempts_str = df.loc[task_id, successful_attempts_col]
    try:
        current_attempts = (
            json.loads(current_attempts_str)
            if current_attempts_str and current_attempts_str != "[]"
            else []
        )
    except (json.JSONDecodeError, TypeError):
        current_attempts = []

    # Add the new successful attempt if not already present
    if attempt_num not in current_attempts:
        current_attempts.append(attempt_num)
        current_attempts.sort()  # Keep attempts sorted

        # Update both columns
        df.loc[task_id, successful_attempts_col] = json.dumps(current_attempts)
        df.loc[task_id, success_count_col] = len(current_attempts)

        print(
            f"Updated success tracking for task {task_id}: successful attempts {current_attempts}, total successes: {len(current_attempts)}"
        )

    df.reset_index(inplace=True)
    try_save_csv(df, get_results_csv_path(output_dir))


def print_execution_summary(output_dir, agent_scope):
    df = pd.read_csv(get_results_csv_path(output_dir))
    for agent in agent_scope:
        print(f"Agent <{agent}>:")

        # Count total tasks for this agent
        total_tasks = len(df)

        # Count completed tasks (attempt 1)
        completion_col = get_col_name_from_template(
            "completion", agent_name=agent, attempt_num=1
        )
        if completion_col in df.columns:
            completed_count = df[completion_col].eq("Y").sum()
        else:
            completed_count = 0

        # Count abnormal exits (attempt 1)
        exit_code_col = get_col_name_from_template(
            "exit_code", agent_name=agent, attempt_num=1
        )
        if exit_code_col in df.columns:
            abnormal_exit_count = df[exit_code_col].ne(0).sum()
        else:
            abnormal_exit_count = 0

        print(f"  - Completed: {completed_count} / {total_tasks}")
        print(f"  - Abnormal exit: {abnormal_exit_count} / {total_tasks}")

        # Show success tracking if available
        success_count_col = f"{agent}_success_count"
        if success_count_col in df.columns:
            successful_tasks = df[success_count_col].gt(0).sum()
            print(f"  - Successful tasks: {successful_tasks} / {total_tasks}")
        else:
            print(f"  - No success tracking data available")


def print_evaluation_summary(output_dir, agent_scope, max_attempts):
    """Prints a summary of the evaluation results, including pass@k."""
    csv_path = get_results_csv_path(output_dir)
    df = pd.read_csv(csv_path)
    print("\n--- Evaluation Summary ---")
    for agent_name in agent_scope:
        print(f"Agent <{agent_name}>:")
        success_count_col = f"{agent_name}_success_count"
        successful_attempts_col = f"{agent_name}_successful_attempts"

        if success_count_col not in df.columns:
            print(f"  - No success tracking data available.")
            continue

        total_tasks = len(df)
        successful_tasks = df[success_count_col] > 0
        print(f"  - Overall Success Rate: {successful_tasks.sum() / total_tasks:.2%}")

        # Calculate pass@k based on successful attempts
        for k in range(1, max_attempts + 1):
            pass_at_k_count = 0
            for idx, row in df.iterrows():
                try:
                    attempts_str = row[successful_attempts_col]
                    successful_attempts = (
                        json.loads(attempts_str)
                        if attempts_str and attempts_str != "[]"
                        else []
                    )
                    # Check if any successful attempt is within the first k attempts
                    if any(attempt <= k for attempt in successful_attempts):
                        pass_at_k_count += 1
                except (json.JSONDecodeError, TypeError):
                    pass

            pass_rate = pass_at_k_count / total_tasks
            print(f"  - Pass@{k}: {pass_at_k_count}/{total_tasks} ({pass_rate:.2%})")

        # Calculate detailed success counts
        print(f"  --- Detailed Success Counts (max_attempts = {max_attempts}) ---")
        success_counts = df[success_count_col]

        for i in range(max_attempts + 1):
            succeeded_n_times = (success_counts == i).sum()
            succeeded_n_times_rate = succeeded_n_times / total_tasks
            plural = "s" if i != 1 else ""
            print(
                f"    - Succeeded {i} time{plural}: {succeeded_n_times}/{total_tasks} ({succeeded_n_times_rate:.2%})"
            )

    print(f"\nEvaluation results have been saved to: {os.path.abspath(csv_path)}")


def is_task_completed(
    output_dir: str,
    task_id: str,
    agent_name: str,
    max_attempts: int,
    reasoning_mode: str,
    action_mode: str,
) -> bool:
    """
    Check if a task is already completed (either succeeded in ≤k attempts or failed all k attempts).

    Parameters:
    - output_dir (str): The directory where the results are stored.
    - task_id (str): The task identifier.
    - agent_name (str): The agent name.
    - max_attempts (int): Maximum number of attempts.
    - reasoning_mode (str): The reasoning mode.
    - action_mode (str): The action mode.

    Returns:
    - bool: True if the task is completed, False otherwise.
    """
    try:
        df = pd.read_csv(get_results_csv_path(output_dir))
        task_row = df[df["task_identifier"] == task_id]

        if task_row.empty:
            return False

        # Check if task already succeeded (has any successful attempts)
        success_count_col = f"{agent_name}_success_count"
        if success_count_col in df.columns:
            success_count = task_row.iloc[0][success_count_col]
            if success_count > 0:
                return True

        # Check if all attempts have been executed
        all_attempts_completed = True
        for attempt in range(1, max_attempts + 1):
            eval_col_prefix = get_col_name_from_template(
                "",
                agent_name=agent_name,
                eval_name=reasoning_mode,
                sub_eval_name=action_mode,
                attempt_num=attempt,
            )
            eval_col_name = f"{eval_col_prefix}_evaluation"

            if eval_col_name not in df.columns:
                all_attempts_completed = False
                break

            eval_result = task_row.iloc[0][eval_col_name]
            if (
                eval_result == "N" or eval_result == "E"
            ):  # Not evaluated yet or evaluation failed
                all_attempts_completed = False
                break

        return all_attempts_completed

    except Exception as e:
        print(f"Error checking task completion for {task_id}: {e}")
        return False


def clear_task_results(
    output_dir: str,
    task_id: str,
    agent_name: str,
    max_attempts: int,
    reasoning_mode: str,
    action_mode: str,
) -> None:
    """
    Clear all results for a specific task and agent.

    Parameters:
    - output_dir (str): The directory where the results are stored.
    - task_id (str): The task identifier.
    - agent_name (str): The agent name.
    - max_attempts (int): Maximum number of attempts.
    - reasoning_mode (str): The reasoning mode.
    - action_mode (str): The action mode.
    """
    try:
        # Clear CSV results
        df = pd.read_csv(get_results_csv_path(output_dir))
        df.set_index("task_identifier", inplace=True)

        if task_id not in df.index:
            print(f"Task {task_id} not found in results CSV.")
            return

        # Reset success tracking columns
        successful_attempts_col = f"{agent_name}_successful_attempts"
        success_count_col = f"{agent_name}_success_count"
        if successful_attempts_col in df.columns:
            df.loc[task_id, successful_attempts_col] = "[]"
        if success_count_col in df.columns:
            df.loc[task_id, success_count_col] = 0

        # Reset all attempt results
        for attempt in range(1, max_attempts + 1):
            # Reset execution columns
            exec_col_prefix = get_col_name_from_template(
                "", agent_name=agent_name, attempt_num=attempt
            )
            exec_columns = [
                f"{exec_col_prefix}_completion",
                f"{exec_col_prefix}_device",
                f"{exec_col_prefix}_exit_code",
                f"{exec_col_prefix}_total_steps",
                f"{exec_col_prefix}_total_token_cost",
                f"{exec_col_prefix}_total_time",
                f"{exec_col_prefix}_finish_signal",
                f"{exec_col_prefix}_step_ratio",
                f"{exec_col_prefix}_elapsed_time_initial",
                f"{exec_col_prefix}_elapsed_time_exec",
                f"{exec_col_prefix}_avg_prompt_tokens",
                f"{exec_col_prefix}_avg_completion_tokens",
                f"{exec_col_prefix}_exec_error",
            ]

            for col in exec_columns:
                if col in df.columns:
                    if (
                        col.endswith("_completion")
                        or col.endswith("_device")
                        or col.endswith("_exec_error")
                    ):
                        df.loc[task_id, col] = "N"
                    elif col.endswith("_exit_code"):
                        df.loc[task_id, col] = -1
                    else:
                        df.loc[task_id, col] = (
                            0 if col.endswith(("_steps", "_signal")) else 0.0
                        )

            # Reset evaluation columns
            eval_col_prefix = get_col_name_from_template(
                "",
                agent_name=agent_name,
                eval_name=reasoning_mode,
                sub_eval_name=action_mode,
                attempt_num=attempt,
            )
            eval_columns = [
                f"{eval_col_prefix}_evaluation",
                f"{eval_col_prefix}_details",
                f"{eval_col_prefix}_evaluation_method",
            ]

            for col in eval_columns:
                if col in df.columns:
                    if col.endswith("_evaluation"):
                        df.loc[task_id, col] = "N"
                    elif col.endswith("_evaluation_method"):
                        df.loc[task_id, col] = ""
                    else:  # details
                        df.loc[task_id, col] = "{}"

        df.reset_index(inplace=True)
        try_save_csv(df, get_results_csv_path(output_dir))

        # Clear output directories
        task_output_dir = os.path.join(output_dir, task_id, agent_name)
        if os.path.exists(task_output_dir):
            shutil.rmtree(task_output_dir)
            print(f"Cleared output directory: {task_output_dir}")

        print(f"Cleared all results for task {task_id} with agent {agent_name}")

    except Exception as e:
        print(f"Error clearing task results for {task_id}: {e}")


def execute_evaluation(
    task_identifier,
    output_dir,
    mode,
    agent_name,
    attempt,
    reasoning_mode,
    action_mode,
    attempt_dir,
    result_overwrite=False,
):
    """
    执行单个评估任务

    Args:
        task_identifier: Task ID
        output_dir: Output directory
        mode: Evaluation mode
        agent_name: Agent name
        attempt: Attempt number
        reasoning_mode: Reasoning mode
        action_mode: Action mode
        attempt_dir: Attempt directory
        result_overwrite: Whether to overwrite existing results
    """
    # 如果不是覆盖模式，先检查是否已有评估结果
    if not result_overwrite:
        current_results_df = get_results_df(output_dir)
        result_col_prefix = get_col_name_from_template(
            "",
            agent_name=agent_name,
            eval_name=reasoning_mode,
            sub_eval_name=action_mode,
            attempt_num=attempt,
        )
        result_col_name = f"{result_col_prefix}_evaluation"

        task_row = current_results_df[
            current_results_df["task_identifier"] == task_identifier
        ]

        if not task_row.empty and result_col_name in task_row.columns:
            eval_result_val = task_row.iloc[0][result_col_name]
            if eval_result_val in ["S", "F", "E"]:  # 已有评估结果
                print(
                    f"Task {task_identifier} agent {agent_name} attempt {attempt} already has evaluation result: {eval_result_val}. Skipping evaluation."
                )
                return True  # 返回True表示不需要重新评估

    # Check if log.json exists before attempting evaluation
    log_json_path = os.path.join(attempt_dir, "log.json")
    if not os.path.exists(log_json_path):
        print(
            f"No log.json found at {log_json_path}. Skipping evaluation for attempt {attempt}."
        )
        return False

    evaluator_path = os.path.join(os.getcwd(), "memgui_eval/evaluator.py")
    python_prefix = shlex.quote(sys.executable)

    command = (
        f'{python_prefix} {evaluator_path} '
        f"--task_identifier {task_identifier} "
        f"--result_dir {output_dir} "
        f"--mode {mode} "
        f"--agent {agent_name} "
        f"--attempt_num {attempt} "
        f"--reasoning_mode {reasoning_mode} "
        f"--action_mode {action_mode}"
    )

    print(f"Evaluating task: {task_identifier}, attempt: {attempt}...")

    eval_process = subprocess.run(command, shell=True, capture_output=True, text=True)

    if eval_process.returncode != 0:
        print(
            f"Evaluation script for attempt {attempt} failed with exit code {eval_process.returncode}."
        )
        print(f"Stderr: {eval_process.stderr}")
        return False

    return True


def immediate_evaluate_and_update_pass_at_k(
    output_dir,
    task_identifier,
    agent_name,
    attempt,
    reasoning_mode,
    action_mode,
    result_overwrite=False,
):
    """
    立即评估任务并更新pass@k状态

    Args:
        output_dir: Output directory
        task_identifier: Task ID
        agent_name: Agent name
        attempt: Attempt number
        reasoning_mode: Reasoning mode
        action_mode: Action mode
        result_overwrite: Whether to overwrite existing results
    """
    attempt_dir = os.path.join(
        output_dir, task_identifier, agent_name, f"attempt_{attempt}"
    )

    # 执行评估
    eval_success = execute_evaluation(
        task_identifier,
        output_dir,
        "full",
        agent_name,
        attempt,
        reasoning_mode,
        action_mode,
        attempt_dir,
        result_overwrite,
    )

    if not eval_success:
        print(f"Evaluation failed for task {task_identifier}, attempt {attempt}")
        return False

    # Record task completion for timing
    try:
        from framework.progress_monitor import record_task_completion

        record_task_completion(task_identifier, "evaluation", output_dir)
    except ImportError:
        pass

    # 读取评估结果
    current_results_df = get_results_df(output_dir)
    result_col_prefix = get_col_name_from_template(
        "",
        agent_name=agent_name,
        eval_name=reasoning_mode,
        sub_eval_name=action_mode,
        attempt_num=attempt,
    )
    result_col_name = f"{result_col_prefix}_evaluation"

    task_row = current_results_df[
        current_results_df["task_identifier"] == task_identifier
    ]

    if task_row.empty or result_col_name not in task_row.columns:
        print(
            f"Could not find result for task {task_identifier} attempt {attempt} in CSV."
        )
        return False

    eval_result_val = task_row.iloc[0][result_col_name]

    if eval_result_val == "S":
        print(f"Task {task_identifier} Attempt {attempt} was successful!")
        update_success_tracking(output_dir, task_identifier, agent_name, attempt)
        return True
    elif eval_result_val == "E":
        print(
            f"Task {task_identifier} Attempt {attempt} resulted in an evaluation error."
        )
    elif eval_result_val == "F":
        print(f"Task {task_identifier} Attempt {attempt} failed evaluation.")
    else:
        print(
            f"Task {task_identifier} Attempt {attempt} has unknown evaluation result: {eval_result_val}"
        )

    return False


def get_valid_attempts(output_dir, task_identifier, agent_name, max_attempts):
    """
    Get list of valid attempts (those with log.json files) for a given task and agent.
    Returns a list of attempt numbers.
    """
    valid_attempts = []
    task_dir = os.path.join(output_dir, task_identifier, agent_name)

    if not os.path.exists(task_dir):
        return valid_attempts

    for attempt in range(1, max_attempts + 1):
        attempt_dir = os.path.join(task_dir, f"attempt_{attempt}")
        log_json_path = os.path.join(attempt_dir, "log.json")

        if os.path.exists(log_json_path):
            valid_attempts.append(attempt)

    return valid_attempts


def check_emulator_crash(attempt_dir):
    """
    检查attempt是否因为emulator中断而失败

    Args:
        attempt_dir: attempt目录路径

    Returns:
        tuple: (is_crash, error_message)
        - is_crash: True表示检测到emulator中断错误
        - error_message: 错误信息（如果有）
    """
    import json

    error_json_path = os.path.join(attempt_dir, "error.json")

    if not os.path.exists(error_json_path):
        return False, None

    try:
        with open(error_json_path, "r", encoding="utf-8") as f:
            error_data = json.load(f)

        # 检查错误信息是否包含emulator相关错误
        emulator_crash_keywords = [
            "Failed to connect to the emulator",
            "emulator connection lost",
            "ADB connection error",
            "device not found",
            "device offline",
            "Connection refused",
            "timeout",
            "socket",
        ]

        for error_item in error_data:
            error_message = error_item.get("error_message", "")
            for keyword in emulator_crash_keywords:
                if keyword.lower() in error_message.lower():
                    return True, error_message

        return False, None

    except Exception as e:
        print(f"Error reading error.json: {e}")
        return False, None


def get_attempt_status(
    output_dir, task_identifier, agent_name, attempt, reasoning_mode, action_mode
):
    """
    检查单个attempt的状态

    Returns:
    - "not_started": attempt还没有开始（没有log.json且没有error.json）
    - "emulator_crash": 因emulator中断而失败，需要重试
    - "executed_not_evaluated": 已经执行但未评估（有log.json但没有评估结果）
    - "executed_and_evaluated": 已经执行且已评估（有log.json且有评估结果）
    - "error": 检查过程中出现错误
    """
    try:
        # 检查是否有log.json文件
        attempt_dir = os.path.join(
            output_dir, task_identifier, agent_name, f"attempt_{attempt}"
        )
        log_json_path = os.path.join(attempt_dir, "log.json")

        # 先检查是否是emulator crash导致的失败
        is_crash, error_message = check_emulator_crash(attempt_dir)
        if is_crash:
            print(
                f"[Emulator Crash Detected] Task {task_identifier}, attempt {attempt}: {error_message}"
            )
            return "emulator_crash"

        if not os.path.exists(log_json_path):
            return "not_started"

        # 检查是否已经评估
        df = pd.read_csv(get_results_csv_path(output_dir))
        task_row = df[df["task_identifier"] == task_identifier]

        if task_row.empty:
            return "executed_not_evaluated"

        eval_col_prefix = get_col_name_from_template(
            "",
            agent_name=agent_name,
            eval_name=reasoning_mode,
            sub_eval_name=action_mode,
            attempt_num=attempt,
        )
        eval_col_name = f"{eval_col_prefix}_evaluation"

        if eval_col_name not in df.columns:
            return "executed_not_evaluated"

        eval_result = task_row.iloc[0][eval_col_name]

        if eval_result in ["S", "F", "E"]:  # 已有评估结果
            return "executed_and_evaluated"
        else:
            return "executed_not_evaluated"

    except Exception as e:
        print(
            f"Error checking attempt {attempt} status for task {task_identifier}: {e}"
        )
        return "error"


def is_task_fully_completed(
    output_dir, task_identifier, agent_name, max_attempts, reasoning_mode, action_mode
):
    """
    检查任务是否已经完全完成（所有k次attempts都已经执行和评估完成）

    注意：根据benchmark策略，无论前面的attempts是否成功，都必须执行满k次attempts

    Returns:
    - True: 所有k次attempts都已完全完成，不需要继续执行
    - False: 还有未完成的attempts，需要继续执行
    """
    try:
        df = pd.read_csv(get_results_csv_path(output_dir))
        task_row = df[df["task_identifier"] == task_identifier]

        if task_row.empty:
            return False

        # 检查所有attempts是否都已经评估完成
        # 注意：移除了早期成功停止的逻辑，确保所有k次attempts都被执行
        for attempt in range(1, max_attempts + 1):
            status = get_attempt_status(
                output_dir,
                task_identifier,
                agent_name,
                attempt,
                reasoning_mode,
                action_mode,
            )
            if status in ["not_started", "executed_not_evaluated"]:
                return False

        return True  # 所有attempts都已评估完成

    except Exception as e:
        print(f"Error checking task completion for {task_identifier}: {e}")
        return False


def collect_evaluation_tasks(
    output_dir,
    agent_scope,
    task_scope,
    max_attempts,
    reasoning_mode,
    action_mode,
    result_overwrite=False,
):
    """
    收集所有需要评估的任务
    """
    eval_tasks = []
    skipped_count = 0

    # 读取当前的结果文件
    current_results_df = get_results_df(output_dir)

    for agent_name in agent_scope:
        for task in task_scope:
            valid_attempts = get_valid_attempts(
                output_dir, task.task_identifier, agent_name, max_attempts
            )

            for attempt in valid_attempts:
                attempt_dir = os.path.join(
                    output_dir, task.task_identifier, agent_name, f"attempt_{attempt}"
                )

                # 检查是否已有评估结果
                if not result_overwrite:
                    result_col_prefix = get_col_name_from_template(
                        "",
                        agent_name=agent_name,
                        eval_name=reasoning_mode,
                        sub_eval_name=action_mode,
                        attempt_num=attempt,
                    )
                    result_col_name = f"{result_col_prefix}_evaluation"

                    # 检查该任务是否已经有评估结果
                    task_row = current_results_df[
                        current_results_df["task_identifier"] == task.task_identifier
                    ]

                    if not task_row.empty and result_col_name in task_row.columns:
                        eval_result_val = task_row.iloc[0][result_col_name]
                        if eval_result_val in ["S", "F", "E"]:  # 已有评估结果
                            print(
                                f"Task {task.task_identifier} agent {agent_name} attempt {attempt} already has evaluation result: {eval_result_val}. Skipping."
                            )
                            skipped_count += 1
                            continue

                # 检查log.json文件是否存在
                log_json_path = os.path.join(attempt_dir, "log.json")
                if not os.path.exists(log_json_path):
                    print(
                        f"No log.json found for task {task.task_identifier} agent {agent_name} attempt {attempt}. Skipping evaluation."
                    )
                    skipped_count += 1
                    continue

                eval_tasks.append(
                    {
                        "task_identifier": task.task_identifier,
                        "agent_name": agent_name,
                        "attempt": attempt,
                        "attempt_dir": attempt_dir,
                        "task": task,
                    }
                )

    print(
        f"收集到 {len(eval_tasks)} 个需要评估的任务，跳过 {skipped_count} 个已有结果或缺少文件的任务"
    )
    return eval_tasks


def process_evaluation_results(
    output_dir, eval_tasks, eval_futures, reasoning_mode, action_mode
):
    """
    处理评估结果并更新成功状态
    """
    print(f"处理 {len(eval_futures)} 个评估任务的结果...")

    for i, future in enumerate(eval_futures):
        eval_task = eval_tasks[i]
        task_identifier = eval_task["task_identifier"]
        agent_name = eval_task["agent_name"]
        attempt = eval_task["attempt"]

        try:
            eval_success = future.result()

            if not eval_success:
                print(
                    f"Evaluation failed for task {task_identifier}, attempt {attempt}"
                )
                continue

            # 读取评估结果
            current_results_df = get_results_df(output_dir)
            result_col_prefix = get_col_name_from_template(
                "",
                agent_name=agent_name,
                eval_name=reasoning_mode,
                sub_eval_name=action_mode,
                attempt_num=attempt,
            )
            result_col_name = f"{result_col_prefix}_evaluation"

            task_row = current_results_df[
                current_results_df["task_identifier"] == task_identifier
            ]

            if task_row.empty or result_col_name not in task_row.columns:
                print(
                    f"Could not find result for task {task_identifier} attempt {attempt} in CSV."
                )
                continue

            eval_result_val = task_row.iloc[0][result_col_name]

            if eval_result_val == "S":
                print(f"Task {task_identifier} Attempt {attempt} was successful!")
                update_success_tracking(
                    output_dir, task_identifier, agent_name, attempt
                )
            elif eval_result_val == "E":
                print(
                    f"Task {task_identifier} Attempt {attempt} resulted in an evaluation error."
                )
            elif eval_result_val == "F":
                print(f"Task {task_identifier} Attempt {attempt} failed evaluation.")
            else:
                print(
                    f"Task {task_identifier} Attempt {attempt} has unknown evaluation result: {eval_result_val}"
                )

        except Exception as e:
            print(
                f"Error processing evaluation result for task {task_identifier}, attempt {attempt}: {e}"
            )


def should_use_self_generated_memory(
    output_dir, task_identifier, agent_name, attempt_num, eval_result
):
    """
    Determines whether to use the agent's self-generated long-term memory.

    Logic:
    - If agent judges success but evaluator judges failure -> use nothing (agent was wrong, don't trust its memory)
    - If both judge failure -> use agent's self-generated memory
    - If evaluator judges success -> no memory needed

    Args:
        output_dir: Output directory
        task_identifier: Task ID
        agent_name: Agent name
        attempt_num: Attempt number
        eval_result: Evaluation result (0 = failure, 1 = success)

    Returns:
        Tuple of (use_self_memory: bool, use_nothing: bool, reason: str)
        - use_self_memory: True if should use agent's self-generated memory
        - use_nothing: True if should not add any hint (agent misjudged)
    """
    attempt_dir = os.path.join(
        output_dir, task_identifier, agent_name, f"attempt_{attempt_num}"
    )

    # Load self-reflection result
    self_reflection_file = os.path.join(attempt_dir, "self_reflection.json")
    if not os.path.exists(self_reflection_file):
        return False, False, "No self-reflection available"

    try:
        with open(self_reflection_file, "r", encoding="utf-8") as f:
            self_reflection = json.load(f)
    except Exception as e:
        return False, False, f"Failed to load self-reflection: {e}"

    self_judgment = self_reflection.get("self_judgment", "unknown")

    # Evaluator says success
    if eval_result == 1:
        return False, False, "Task succeeded, no memory needed"

    # Evaluator says failure
    if self_judgment == "success":
        # Agent thought it succeeded but it failed -> agent was wrong, don't add any hint
        return False, True, "Agent misjudged success, not adding any hint"
    elif self_judgment == "failure":
        # Both agree it failed -> use agent's memory
        return True, False, "Both agree on failure, using self-generated memory"
    else:
        # Unknown judgment -> don't add anything
        return (
            False,
            True,
            f"Unknown self-judgment: {self_judgment}, not adding any hint",
        )


def reconcile_memory_with_eval(
    output_dir, task_identifier, agent_name, attempt_num, eval_result
):
    """
    Reconciles the agent's self-generated memory with the evaluator's result.
    Creates a final long_term_memory.json that will be used for the next attempt.

    Logic:
    - If task succeeded: remove long_term_memory.json
    - If agent misjudged (thought success but actually failed): remove long_term_memory.json (don't add any hint)
    - If both agree on failure: keep agent's self-generated memory

    Args:
        output_dir: Output directory
        task_identifier: Task ID
        agent_name: Agent name
        attempt_num: Attempt number
        eval_result: Evaluation result (0 = failure, 1 = success)

    Returns:
        Path to the reconciled memory file, or None
    """
    attempt_dir = os.path.join(
        output_dir, task_identifier, agent_name, f"attempt_{attempt_num}"
    )

    use_self_memory, use_nothing, reason = should_use_self_generated_memory(
        output_dir, task_identifier, agent_name, attempt_num, eval_result
    )

    print(f"[Memory Reconciliation] Attempt {attempt_num}: {reason}")

    ltm_file = os.path.join(attempt_dir, "long_term_memory.json")

    if eval_result == 1:
        # Task succeeded, remove any existing long_term_memory.json to prevent confusion
        if os.path.exists(ltm_file):
            os.remove(ltm_file)
            print(
                f"[Memory Reconciliation] Removed long_term_memory.json (task succeeded)"
            )
        return None

    if use_nothing:
        # Agent misjudged, remove long_term_memory.json - don't add any hint
        if os.path.exists(ltm_file):
            os.remove(ltm_file)
            print(
                f"[Memory Reconciliation] Removed long_term_memory.json (agent misjudged, not adding any hint)"
            )
        return None

    if use_self_memory:
        # Agent's memory is valid, keep it as is
        if os.path.exists(ltm_file):
            print(f"[Memory Reconciliation] Using self-generated memory: {ltm_file}")
            return ltm_file

    return None


def generate_long_term_memory_with_eval(
    attempt_dir: str,
    task_description: str,
    eval_result: int,
    config: dict,
) -> dict:
    """
    Generate long-term memory (self-reflection) after evaluation is complete.

    This function is called after evaluation to generate self-reflection with the
    knowledge of whether the task succeeded or failed.

    Args:
        attempt_dir: Directory where attempt results are stored.
        task_description: The task description.
        eval_result: Evaluation result (0 = failure, 1 = success).
        config: Configuration dict with QWEN_BASE_URL, QWEN_API_KEY, QWEN_MODEL.

    Returns:
        Dictionary containing self-reflection results, or None if failed.
    """
    import base64
    import glob
    from openai import OpenAI
    from PIL import Image, ImageDraw, ImageFont

    print("=" * 60)
    result_str = "SUCCESS" if eval_result == 1 else "FAILURE"
    print(
        f"[Long-Term Memory] Generating self-reflection with eval result: {result_str}"
    )
    print("=" * 60)

    # Read execution history from log.json or detailed_model_logs.json
    execution_history = []
    log_json_path = os.path.join(attempt_dir, "log.json")
    detailed_logs_path = os.path.join(attempt_dir, "detailed_model_logs.json")

    if os.path.exists(log_json_path):
        try:
            with open(log_json_path, "r", encoding="utf-8") as f:
                log_data = json.load(f)
            for entry in log_data:
                if isinstance(entry, dict) and "step" in entry:
                    ui_obs = "N/A"
                    action_intent = "N/A"

                    # First try to get from direct fields
                    if entry.get("ui_observation"):
                        ui_obs = entry.get("ui_observation")
                    if entry.get("action_intent"):
                        action_intent = entry.get("action_intent")

                    # If not found, extract from action_output or raw_response
                    if ui_obs == "N/A" or action_intent == "N/A":
                        text_to_parse = entry.get("action_output", "") or entry.get(
                            "raw_response", ""
                        )
                        if text_to_parse:
                            # Extract ui_observation
                            if ui_obs == "N/A":
                                ui_match = re.search(
                                    r"<ui_observation>(.*?)</ui_observation>",
                                    text_to_parse,
                                    re.DOTALL,
                                )
                                if ui_match:
                                    ui_obs = ui_match.group(1).strip()
                            # Extract action_intent
                            if action_intent == "N/A":
                                intent_match = re.search(
                                    r"<action_intent>(.*?)</action_intent>",
                                    text_to_parse,
                                    re.DOTALL,
                                )
                                if intent_match:
                                    action_intent = intent_match.group(1).strip()

                    execution_history.append(
                        {
                            "step": entry.get("step"),
                            "ui_observation": ui_obs,
                            "action_intent": action_intent,
                        }
                    )
        except Exception as e:
            print(f"[Long-Term Memory] Warning: Could not read log.json: {e}")

    if not execution_history and os.path.exists(detailed_logs_path):
        try:
            with open(detailed_logs_path, "r", encoding="utf-8") as f:
                detailed_logs = json.load(f)
            for entry in detailed_logs:
                if isinstance(entry, dict) and "step" in entry:
                    # Try to extract from response
                    response = entry.get("response", "")
                    ui_obs = "N/A"
                    action_intent = "N/A"

                    # Extract ui_observation
                    ui_match = re.search(
                        r"<ui_observation>(.*?)</ui_observation>", response, re.DOTALL
                    )
                    if ui_match:
                        ui_obs = ui_match.group(1).strip()

                    # Extract action_intent
                    intent_match = re.search(
                        r"<action_intent>(.*?)</action_intent>", response, re.DOTALL
                    )
                    if intent_match:
                        action_intent = intent_match.group(1).strip()

                    execution_history.append(
                        {
                            "step": entry.get("step"),
                            "ui_observation": ui_obs,
                            "action_intent": action_intent,
                        }
                    )
        except Exception as e:
            print(
                f"[Long-Term Memory] Warning: Could not read detailed_model_logs.json: {e}"
            )

    if not execution_history:
        print("[Long-Term Memory] Warning: No execution history available")

    # Generate puzzle image
    puzzle_path = None
    puzzle_base64 = None
    last_screenshots = []
    labels = []

    # Helper function for numbered pattern (0.png, 1.png, ...)
    def get_step_num_from_numbered_pattern(filepath):
        """Extract step number from X.png pattern (0.png, 1.png, ...)"""
        match = re.match(r"^(\d+)\.png$", os.path.basename(filepath))
        return int(match.group(1)) if match else -1

    # Use raw screenshots in attempt_dir (0.png, 1.png, ...)
    print(f"[Long-Term Memory] Looking for screenshots in: {attempt_dir}")
    raw_screenshots = glob.glob(os.path.join(attempt_dir, "*.png"))
    # Filter for numbered pattern (0.png, 1.png, ...) and exclude other PNGs
    raw_screenshots = [
        f for f in raw_screenshots if get_step_num_from_numbered_pattern(f) >= 0
    ]
    raw_screenshots.sort(key=get_step_num_from_numbered_pattern)

    if raw_screenshots:
        last_screenshots = raw_screenshots[-3:]
        # Note: numbered files are 0-indexed, step labels are 1-indexed
        labels = [
            f"Step {get_step_num_from_numbered_pattern(p) + 1}"
            for p in last_screenshots
        ]
        print(f"[Long-Term Memory] Using {len(last_screenshots)} raw screenshots")
    else:
        print(f"[Long-Term Memory] Warning: No screenshots found in {attempt_dir}")

    if last_screenshots:
        try:
            # Stitch images
            images = [Image.open(p) for p in last_screenshots]
            widths, heights = zip(*(i.size for i in images))
            total_width = sum(widths)
            max_height = max(heights)
            label_height = 80

            new_im = Image.new("RGB", (total_width, max_height + label_height), "white")
            draw = ImageDraw.Draw(new_im)

            try:
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", size=60)
            except IOError:
                font = ImageFont.load_default(size=40)

            x_offset = 0
            for i, im in enumerate(images):
                new_im.paste(im, (x_offset, label_height))
                label = labels[i]
                text_bbox = draw.textbbox((0, 0), label, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_x = x_offset + (im.width - text_width) // 2
                draw.text((text_x, 10), label, fill="black", font=font)
                x_offset += im.size[0]

            # Save puzzle
            puzzle_dir = os.path.join(attempt_dir, "puzzle")
            os.makedirs(puzzle_dir, exist_ok=True)
            puzzle_path = os.path.join(puzzle_dir, "self_reflection_puzzle.png")
            new_im.save(puzzle_path)

            # Convert to base64
            import io

            buffer = io.BytesIO()
            new_im.save(buffer, format="PNG")
            puzzle_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            print(f"[Long-Term Memory] Generated puzzle image: {puzzle_path}")
        except Exception as e:
            print(f"[Long-Term Memory] Warning: Could not generate puzzle: {e}")
            import traceback

            traceback.print_exc()

    # Fallback: try to use existing puzzle image if self_reflection_puzzle wasn't generated
    if not puzzle_base64:
        fallback_puzzles = [
            os.path.join(attempt_dir, "puzzle", "pre_eval_puzzle.png"),
            os.path.join(attempt_dir, "puzzle", "puzzle.png"),
        ]
        for fallback_path in fallback_puzzles:
            if os.path.exists(fallback_path):
                try:
                    with open(fallback_path, "rb") as f:
                        puzzle_base64 = base64.b64encode(f.read()).decode("utf-8")
                    puzzle_path = fallback_path
                    print(
                        f"[Long-Term Memory] Using fallback puzzle image: {fallback_path}"
                    )
                    break
                except Exception as e:
                    print(
                        f"[Long-Term Memory] Warning: Could not load fallback puzzle: {e}"
                    )

    # Format execution history
    history_text = ""
    for step_info in execution_history:
        step_num = step_info.get("step", "?")
        ui_obs = step_info.get("ui_observation", "N/A")
        action_intent = step_info.get("action_intent", "N/A")
        history_text += f"\n[Step {step_num}]\n"
        history_text += f"  UI Observation: {ui_obs}\n"
        history_text += f"  Action Intent: {action_intent}\n"

    # Build prompts
    if eval_result == 1:
        system_prompt = """You are a self-reflective GUI agent analyzing your own task execution.

The evaluator has determined that the task was completed successfully.

Your job is to briefly summarize what you did well in this execution.

Output a JSON object with:
- "self_judgment": "success" (confirmed by evaluator)
- "reasoning": Brief summary of what was done correctly
- "key_observations": List of key observations from execution
- "long_term_memory": null (not needed for successful tasks)
"""
    else:
        system_prompt = """You are a self-reflective GUI agent analyzing your own task execution.

The evaluator has determined that the task FAILED. Your job is to analyze what went wrong and provide constructive hints for the next attempt.

Be honest and critical in your self-assessment. Look at:
- What actions were taken that didn't achieve the goal?
- Were there any errors or inefficiencies?
- What should be done differently next time?

Output a JSON object with:
- "self_judgment": "failure" (confirmed by evaluator)
- "reasoning": Brief explanation of what went wrong
- "key_observations": List of key observations from execution
- "long_term_memory": Hints for next attempt (REQUIRED since task failed)
  - "key_mistake": What was the main mistake
  - "what_to_avoid": List of things to avoid
  - "suggested_approach": List of alternative approaches
  - "important_insights": List of key insights
  - "hint_summary": Brief summary hint for next attempt
"""

    eval_status_text = f"\n## Evaluator Result\nThe task was judged as: **{'SUCCESS' if eval_result == 1 else 'FAILURE'}**\n"

    user_prompt = f"""## Task Description
{task_description}
{eval_status_text}
## Execution History
{history_text}

## Final Screenshots
[Puzzle image attached showing the last 3 screenshots]

## Your Task"""

    if eval_result == 1:
        user_prompt += "\nSummarize what you did well in this successful execution.\n"
    else:
        user_prompt += "\nThe task FAILED. Analyze what went wrong and generate helpful hints for the next attempt.\n"

    user_prompt += "\nOutput your analysis as a JSON object."

    # Build messages
    messages = [{"role": "system", "content": system_prompt}]

    if puzzle_base64:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{puzzle_base64}"},
                    },
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": user_prompt})

    # Call model
    try:
        client = OpenAI(
            base_url=config.get("QWEN_BASE_URL"),
            api_key=config.get("QWEN_API_KEY"),
        )

        response = client.chat.completions.create(
            model=config.get("QWEN_MODEL"),
            messages=messages,
        )

        response_str = response.choices[0].message.content or ""
        print(f"[Long-Term Memory] Self-reflection response received")

        # Extract reasoning_content if available
        reasoning_content = None
        message = response.choices[0].message
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            reasoning_content = message.reasoning_content

        # Parse JSON
        try:
            json_match = re.search(r"\{[\s\S]*\}", response_str)
            if json_match:
                reflection_data = json.loads(json_match.group())
            else:
                reflection_data = {"raw_response": response_str}
        except json.JSONDecodeError:
            reflection_data = {"raw_response": response_str}

        reflection_data["execution_history"] = execution_history
        reflection_data["eval_result"] = eval_result

        # Save reflection
        reflection_output_path = os.path.join(attempt_dir, "self_reflection.json")
        with open(reflection_output_path, "w", encoding="utf-8") as f:
            json.dump(reflection_data, f, indent=4, ensure_ascii=False)

        # Save detailed log
        reflection_log = {
            "type": "self_reflection",
            "request_messages": messages,
            "puzzle_path": puzzle_path,
            "response": response_str,
            "reasoning_content": reasoning_content,
        }

        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            reflection_log["prompt_tokens"] = getattr(usage, "prompt_tokens", 0)
            reflection_log["completion_tokens"] = getattr(usage, "completion_tokens", 0)
            reflection_log["total_tokens"] = getattr(usage, "total_tokens", 0)
            try:
                if hasattr(usage, "model_dump"):
                    reflection_log["usage_raw"] = usage.model_dump()
                elif hasattr(usage, "__dict__"):
                    reflection_log["usage_raw"] = dict(usage.__dict__)
            except Exception:
                pass

        detailed_log_path = os.path.join(attempt_dir, "self_reflection_detailed.json")
        with open(detailed_log_path, "w", encoding="utf-8") as f:
            json.dump(reflection_log, f, indent=4, ensure_ascii=False)

        print(f"[Long-Term Memory] Self-reflection saved to {reflection_output_path}")

        # If failure, save long_term_memory.json
        if eval_result == 0 and reflection_data.get("long_term_memory"):
            ltm = reflection_data["long_term_memory"]
            ltm_output_path = os.path.join(attempt_dir, "long_term_memory.json")
            ltm_data = {
                "source": "self_reflection",
                "self_judgment": reflection_data.get("self_judgment", "failure"),
                "eval_result": eval_result,
                "task_instruction": task_description,  # 保存任务指令
                **ltm,
            }
            with open(ltm_output_path, "w", encoding="utf-8") as f:
                json.dump(ltm_data, f, indent=4, ensure_ascii=False)
            print(f"[Long-Term Memory] Long-term memory saved to {ltm_output_path}")
        elif eval_result == 0:
            print(
                "[Long-Term Memory] Warning: Task failed but no long_term_memory generated"
            )
        else:
            print("[Long-Term Memory] Task succeeded, no long-term memory needed")

        # Add token statistics to return data
        reflection_data["_token_stats"] = {
            "prompt_tokens": reflection_log.get("prompt_tokens", 0),
            "completion_tokens": reflection_log.get("completion_tokens", 0),
            "total_tokens": reflection_log.get("total_tokens", 0),
        }

        return reflection_data

    except Exception as e:
        print(f"[Long-Term Memory] Error generating self-reflection: {e}")
        import traceback

        traceback.print_exc()
        return None


@with_filelock()
def save_self_reflection_result(
    output_dir: str,
    task_id: str,
    agent_name: str,
    attempt_num: int,
    reflection_data: dict,
) -> pd.DataFrame:
    """
    Save self-reflection results to results.csv.

    Args:
        output_dir: The directory where the results are stored.
        task_id: The task identifier.
        agent_name: The agent name.
        attempt_num: The attempt number.
        reflection_data: The reflection data returned from generate_long_term_memory_with_eval.

    Returns:
        The updated DataFrame.
    """
    csv_path = get_results_csv_path(output_dir)
    if not os.path.exists(csv_path):
        print(f"[Self-Reflection] Warning: results.csv not found at {csv_path}")
        return None

    df = pd.read_csv(csv_path)
    df.set_index("task_identifier", inplace=True)

    if task_id not in df.index:
        print(f"[Self-Reflection] Warning: task_id {task_id} not found in results.csv")
        df.reset_index(inplace=True)
        return df

    prefix = get_col_name_from_template(
        "", agent_name=agent_name, attempt_num=attempt_num
    )

    # Save self-reflection judgment
    self_judgment = reflection_data.get("self_judgment", "")
    df.loc[task_id, f"{prefix}_self_reflection_judgment"] = self_judgment

    # Save token statistics
    token_stats = reflection_data.get("_token_stats", {})
    prompt_tokens = token_stats.get("prompt_tokens", 0)
    completion_tokens = token_stats.get("completion_tokens", 0)
    total_tokens = token_stats.get("total_tokens", 0)

    df.loc[task_id, f"{prefix}_self_reflection_prompt_tokens"] = prompt_tokens
    df.loc[task_id, f"{prefix}_self_reflection_completion_tokens"] = completion_tokens
    df.loc[task_id, f"{prefix}_self_reflection_total_tokens"] = total_tokens

    # Calculate API cost (using rough estimates similar to action execution)
    # Using $0.01 per 1K prompt tokens, $0.03 per 1K completion tokens
    prompt_cost = (prompt_tokens / 1000) * 0.01
    completion_cost = (completion_tokens / 1000) * 0.03
    df.loc[task_id, f"{prefix}_self_reflection_api_cost"] = (
        prompt_cost + completion_cost
    )

    df.reset_index(inplace=True)
    try_save_csv(df, csv_path)

    print(
        f"[Self-Reflection] Saved results for {task_id} attempt {attempt_num}: "
        f"judgment={self_judgment}, prompt_tokens={prompt_tokens}, "
        f"completion_tokens={completion_tokens}"
    )

    return df
