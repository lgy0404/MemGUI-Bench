import subprocess
import os
from . import utils
import shutil
from collections import namedtuple


class BaseAgent:
    """This is an abstract class for base agent.

    Attributes:
    agent_name (str): The name of the agent.
    default_adb_keyboard (bool): Whether the agent should use ADBKeyboard by default.
    config (dict): The configuration loaded from config.yaml.
    agent_config (dict): The specific configuration for this agent.
    repo_abs_path (str): The absolute path to the repository of this agent.
    """

    agent_name = ""
    default_adb_keyboard = False

    def __init__(self, config):
        # config loaded from config.yaml
        self.config = config
        self.agent_config = utils.get_agent_config(self.config, self.agent_name)
        self.repo_abs_path = os.path.join(os.getcwd(), self.agent_config["REPO_PATH"])
        super().__init__()

    def construct_command(
        self,
        task: namedtuple,
        full_task_description: str,
        output_dir: str,
        device: dict,
    ) -> tuple[str, str]:
        """Abstract method to construct and return a command string to execute the agent's Python
        code.

        Parameters:
        - task (namedtuple): A named tuple containing task information.
        - full_task_description (str): The modified task description to be sent to agents.
        - output_dir (str): The directory where the output should be saved.
        - device (dict) : The android device.

        Returns:
        - tuple[str, str]: A command string and its arguments to run the agent's Python code.

        Note: This method should be overridden in subclasses to provide the specific command required
        for executing the agent's code.
        """
        raise Exception("NOT IMPLEMENTED")

    def setup_keyboard(self, device_serial, task_lang=None):
        if task_lang == "CHN" or self.default_adb_keyboard:
            utils.set_adb_keyboard(device_serial)
        else:
            utils.set_default_keyboard(
                device_serial, self.config["DEFAULT_KEYBOARD_PACKAGE"]
            )

    def execute_task(
        self,
        task: namedtuple,
        device: dict,
        output_dir: str,
        capture_stdout=True,
    ) -> tuple[bool, int]:
        """Executes the task by constructing the command and running it in a subprocess.

        Parameters:
        - task (namedtuple): A named tuple with the following fields:
            - task_identifier (str)
            - task_app (str)
            - adb_app (str)
            - adb_home_page (str)
            - task_language (str)
            - task_description (str)
            - task_difficulty  (int)
            - golden_steps (int)
            - key_component_final (List[str])
            - is_cross_app (str)
        - device (dict) : The android device:
            - serial (str)
            - console_port (int): is None if the device is not an emulator set up by this framework
            - grpc_port (int): is None if the device is not an emulator set up by this framework
        - output_dir (str): The directory where the output should be saved for this attempt.
        - capture_stdout (bool): Whether to capture stdout and stderr from subprocess using subprocess.PIPE

        Returns:
        - tuple[bool, int]:
            - boolean indicates whether task is completed
            - exit_code:
                0 - Finished, no rerun (Task completed)
                1 - Unexpected error, rerun decision needed (Task incomplete)
                2 - Expected error, no rerun (Task completed)
                3 - Expected error, rerun required (Task incomplete)
                4 - Max rounds reached, no rerun (Task completed)
        """
        # Only access task_language if it exists, otherwise use None (default behavior)
        task_language = getattr(task, "task_language", None)
        self.setup_keyboard(device["serial"], task_language)

        is_linux = os.name == "posix"
        if is_linux:
            env = f"""export PATH="{self.config["CONDA_PATH"]}/bin:$PATH" && source activate && conda deactivate && conda activate {self.agent_config["ENV_NAME"]}"""
        else:
            env = f"""conda activate {self.agent_config["ENV_NAME"]}"""

        script, args = self.construct_command(
            task, task.task_description, output_dir, device
        )
        command = f"{env} && python {script} {args}"

        print(command)
        if is_linux:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.repo_abs_path,
                executable="/bin/bash",
                stdout=subprocess.PIPE if capture_stdout else None,
                stderr=subprocess.PIPE if capture_stdout else None,
            )
        else:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.repo_abs_path,
                stdout=subprocess.PIPE if capture_stdout else None,
                stderr=subprocess.PIPE if capture_stdout else None,
            )

        stdout, stderr = process.communicate()

        if stdout:
            stdout = safe_decode(stdout).replace("\r\n", "\n")  # CRLF to LF

        if stderr:
            stderr = safe_decode(stderr).replace("\r\n", "\n")  # CRLF to LF

        if stdout:
            with open(output_dir + "/stdout.txt", "w", encoding="utf-8") as file:
                file.write(f"<{self.agent_name}>\n")
                file.write(stdout)
        if stderr:
            with open(output_dir + "/stderr.txt", "w", encoding="utf-8") as file:
                file.write(f"<{self.agent_name}>\n")
                file.write(stderr)

        return (process.returncode in [0, 2, 4], process.returncode)


def safe_decode(byte_data, encoding_list=["utf-8", "gbk"]):
    for encoding in encoding_list:
        try:
            return byte_data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"Unable to decode with encodings: {encoding_list}")


class AppAgent(BaseAgent):
    agent_name = "AppAgent"

    def construct_command(
        self,
        task: namedtuple,
        full_task_description: str,
        output_dir: str,
        device: dict,
    ) -> tuple[str, str]:
        script = "scripts/task_executor.py"
        # TODO: Escaping double quotes works for Windows Only, use '\' as escape characters otherwise

        max_rounds = self.config["MAX_ROUNDS"]
        if not max_rounds:
            max_rounds = int(task.golden_steps * 2.5 + 1)

        # Handle optional fields that may not exist in simplified dataset
        task_app = getattr(task, "task_app", "unknown")
        task_language = getattr(task, "task_language", "ENG")

        args = (
            f"""--openai_api_key {self.config["OPENAI_API_KEY"]} """
            f"""--task "{full_task_description.replace('"', '""')}" """
            f'--app "{task_app}" '
            f'--lang "{task_language}" '
            f'--output_dir "{output_dir}" '
            f"--root_dir ./ "
            f"--max_rounds {max_rounds} "
            f"""--device {device["serial"]} """
        )
        return script, args


class AutoDroid(BaseAgent):
    agent_name = "AutoDroid"

    def execute_task(
        self,
        task: namedtuple,
        device: dict,
        output_dir: str,
        capture_stdout=True,
    ) -> tuple[bool, int]:
        # May configure `capture_stdout` to False to make it work on some operating systems
        return super().execute_task(task, device, output_dir, capture_stdout)

    def construct_command(
        self,
        task: namedtuple,
        full_task_description: str,
        output_dir: str,
        device: dict,
    ) -> tuple[str, str]:
        script = "start.py"
        tmp_dir = "./tmp"  # TODO: 通过重载 def execute_task(self, task: namedtuple): 在执行完之后删除tmp文件夹
        os.makedirs(tmp_dir, exist_ok=True)
        # to absolute path
        tmp_dir = os.path.abspath(tmp_dir)

        # Handle optional fields that may not exist in simplified dataset
        adb_app = getattr(task, "adb_app", "unknown")
        task_apk_path = os.path.join(tmp_dir, adb_app + ".apk")
        autodroid_tmp_dir = os.path.join(
            tmp_dir, f"autodroid_tmp_{device['serial'].replace(':', '_')}"
        )  # support multiple devices
        if os.path.exists(autodroid_tmp_dir):
            shutil.rmtree(autodroid_tmp_dir)
        os.makedirs(autodroid_tmp_dir, exist_ok=True)

        if adb_app != "unknown" and not os.path.exists(task_apk_path):
            print(f"Extracting apk to: {task_apk_path}, this may take a while...")
            res = utils.get_apk(device["serial"], adb_app, task_apk_path)
            if os.path.exists(task_apk_path):
                print(f"APK extracted to: {task_apk_path}")
            assert res != "ERROR"

        max_rounds = self.config["MAX_ROUNDS"]
        if not max_rounds:
            max_rounds = int(task.golden_steps * 2.5 + 1)
        args = (
            f""" -task "{full_task_description.replace('"', '""')}" """
            f' -a "{task_apk_path}" '
            f' -benchmark_output_dir "{output_dir}" '
            f' -o "{autodroid_tmp_dir}" '
            f" -max_rounds {max_rounds} "
            f" -keep_app "
            f""" -d {device["serial"]} """
        )
        if "emulator" in device["serial"]:
            args += " -is_emulator "
        return script, args


class MobileAgent(BaseAgent):
    agent_name = "MobileAgent"
    default_adb_keyboard = True

    def construct_command(
        self,
        task: namedtuple,
        full_task_description: str,
        output_dir: str,
        device: dict,
    ) -> tuple[str, str]:
        script = "run.py"
        # TODO: Escaping double quotes works for Windows Only, use '\' as escape characters otherwise

        max_rounds = self.config["MAX_ROUNDS"]
        if not max_rounds:
            max_rounds = int(task.golden_steps * 2.5 + 1)

        # Handle optional fields that may not exist in simplified dataset
        task_language = getattr(task, "task_language", "ENG")

        args = (
            f"""--api {self.config["OPENAI_API_KEY"]} """
            f"""--instruction "{full_task_description.replace('"', '""')}" """
            f'--lang "{task_language}" '
            f'--output_dir "{output_dir}" '
            f"""--adb_path "{self.config["ADB_PATH"]}" """
            f"--max_rounds {max_rounds} "
            f"""--device {device["serial"]} """
        )
        return script, args


class MobileAgentV2(BaseAgent):
    agent_name = "MobileAgentV2"
    default_adb_keyboard = True

    def construct_command(
        self,
        task: namedtuple,
        full_task_description: str,
        output_dir: str,
        device: dict,
    ) -> tuple[str, str]:
        script = "run.py"
        # TODO: Escaping double quotes works for Windows Only, use '\' as escape characters otherwise

        max_rounds = self.config["MAX_ROUNDS"]
        if not max_rounds:
            max_rounds = int(task.golden_steps * 2.5 + 1)

        # Handle optional fields that may not exist in simplified dataset
        task_language = getattr(task, "task_language", "ENG")

        args = (
            f"""--openai_api_key {self.config["OPENAI_API_KEY"]} """
            f"""--qwen_api_key {self.config["QWEN_API_KEY"]} """
            f"""--instruction "{full_task_description.replace('"', '""')}" """
            f'--lang "{task_language}" '
            f'--output_dir "{output_dir}" '
            f"""--adb_path "{self.config["ADB_PATH"]}" """
            f"--max_rounds {max_rounds} "
            f"""--device {device["serial"]} """
        )
        return script, args


class AndroidWorldAgent(BaseAgent):
    agent_name = ""

    def construct_command(
        self,
        task: namedtuple,
        full_task_description: str,
        output_dir: str,
        device: dict,
    ) -> tuple[str, str]:
        script = "benchmark_run.py"

        max_rounds = self.config["MAX_ROUNDS"]
        if not max_rounds:
            max_rounds = int(task.golden_steps * 2 + 1)

        # Handle optional fields that may not exist in simplified dataset
        task_language = getattr(task, "task_language", "ENG")

        # TODO: Escaping double quotes works for Windows Only, use '\' as escape characters otherwise
        args = (
            f"""--task "{full_task_description.replace('"', '""')}" """
            f'--lang "{task_language}" '
            f'--output_dir "{output_dir}" '
            f"""--adb_path "{self.config["ADB_PATH"]}" """
            f"--max_rounds {max_rounds} "
            f'--agent "{self.agent_name}" '
        )
        openai_api_key = self.config.get("OPENAI_API_KEY")
        if openai_api_key:
            args = f"""--openai_api_key "{openai_api_key}" """ + args
        if device["serial"].startswith("emulator-"):
            args += f"""--device_console_port {device["console_port"]}  --device_grpc_port {device["grpc_port"]} """
        else:
            args += f"""--device_serial {device["serial"]} """

        # Add UI-TARS specific configuration parameters - all required
        if self.agent_name in ["UITARS", "UITARS_1_5"]:
            if "UITARS_BASE_URL" not in self.config:
                raise ValueError(
                    f"UITARS_BASE_URL must be specified in config for {self.agent_name} agent"
                )
            if "UITARS_API_KEY" not in self.config:
                raise ValueError(
                    f"UITARS_API_KEY must be specified in config for {self.agent_name} agent"
                )
            if "UITARS_MODEL" not in self.config:
                raise ValueError(
                    f"UITARS_MODEL must be specified in config for {self.agent_name} agent"
                )
            if "UITARS_HISTORY_N" not in self.config:
                raise ValueError(
                    f"UITARS_HISTORY_N must be specified in config for {self.agent_name} agent"
                )

            args += f"""--uitars_base_url "{self.config["UITARS_BASE_URL"]}" """
            args += f"""--uitars_api_key "{self.config["UITARS_API_KEY"]}" """
            args += f"""--uitars_model "{self.config["UITARS_MODEL"]}" """
            args += f"""--uitars_history_n {self.config["UITARS_HISTORY_N"]} """

        # Add M3A specific configuration parameters - all required
        if self.agent_name in ["M3A", "M3A_vivo_gemini", "M3A_MultiTurn"]:
            if "M3A_MODEL" not in self.config:
                raise ValueError(
                    f"M3A_MODEL must be specified in config for {self.agent_name} agent"
                )
            if "M3A_BASE_URL" not in self.config:
                raise ValueError(
                    f"M3A_BASE_URL must be specified in config for {self.agent_name} agent"
                )
            if "M3A_API_KEY" not in self.config:
                raise ValueError(
                    f"M3A_API_KEY must be specified in config for {self.agent_name} agent"
                )

            args += f"""--m3a_model "{self.config["M3A_MODEL"]}" """
            args += f"""--m3a_base_url "{self.config["M3A_BASE_URL"]}" """
            args += f"""--m3a_api_key "{self.config["M3A_API_KEY"]}" """

        # Add Qwen3VL specific configuration parameters - all required
        if self.agent_name == "Qwen3VL":
            if "QWEN_BASE_URL" not in self.config:
                raise ValueError(
                    f"QWEN_BASE_URL must be specified in config for {self.agent_name} agent"
                )
            if "QWEN_API_KEY" not in self.config:
                raise ValueError(
                    f"QWEN_API_KEY must be specified in config for {self.agent_name} agent"
                )
            if "QWEN_MODEL" not in self.config:
                raise ValueError(
                    f"QWEN_MODEL must be specified in config for {self.agent_name} agent"
                )

            args += f"""--qwen_base_url "{self.config["QWEN_BASE_URL"]}" """
            args += f"""--qwen_api_key "{self.config["QWEN_API_KEY"]}" """
            args += f"""--qwen_model "{self.config["QWEN_MODEL"]}" """
        return script, args


class M3A(AndroidWorldAgent):
    agent_name = "M3A"


class M3A_vivo_gemini(AndroidWorldAgent):
    agent_name = "M3A_vivo_gemini"


class T3A_vivo_gemini(AndroidWorldAgent):
    agent_name = "T3A_vivo_gemini"


class M3A_MultiTurn(AndroidWorldAgent):
    agent_name = "M3A_MultiTurn"


class T3A(AndroidWorldAgent):
    agent_name = "T3A"


class SeeAct(AndroidWorldAgent):
    agent_name = "SeeAct"


class UITARS(AndroidWorldAgent):
    agent_name = "UITARS"


class UITARS_1_5(AndroidWorldAgent):
    agent_name = "UITARS_1_5"


class Qwen3VL(AndroidWorldAgent):
    agent_name = "Qwen3VL"


class AgentAsAModel(BaseAgent):
    agent_name = ""

    def construct_command(
        self,
        task: namedtuple,
        full_task_description: str,
        output_dir: str,
        device: dict,
    ) -> tuple[str, str]:
        script = "task_executor.py"
        max_rounds = self.config["MAX_ROUNDS"]
        if not max_rounds:
            max_rounds = int(task.golden_steps * 2.5 + 1)
        args = (
            f""" -task "{full_task_description.replace('"', '""')}" """
            f' -benchmark_output_dir "{output_dir}" '
            f" -max_rounds {max_rounds} "
            f""" -device {device["serial"]} """
            f" -model_api_url {self.agent_config['API_URL']} "
        )
        return script, args


class AutoUI(AgentAsAModel):
    agent_name = "AutoUI"


class DigiRLAgent(AgentAsAModel):
    agent_name = "DigiRLAgent"


class CogAgent(AgentAsAModel):
    agent_name = "CogAgent"


class GUI_Odyssey(AgentAsAModel):
    agent_name = "GUI_Odyssey"
