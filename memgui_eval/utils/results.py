"""Minimal result helpers used by the MemGUI-Eval compatibility workspace.

The MobileWorld runner owns task execution and trajectory logging. MemGUI-Eval
still writes a legacy `results.csv` inside `_memgui_eval/` so its original
metrics can run unchanged. This module keeps only those CSV update helpers and
intentionally avoids the old MemGUI runner/AVD/agent orchestration code.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import pandas as pd
from filelock import FileLock


def get_results_csv_path(output_dir: str) -> str:
    return os.path.join(output_dir, "results.csv")


def get_col_name_from_template(
    template_name: str,
    agent_name: str | None = None,
    eval_name: str | None = None,
    sub_eval_name: str | None = None,
    attempt_num: int | None = None,
) -> str:
    parts = []
    if agent_name:
        parts.append(agent_name)
    if eval_name:
        parts.append(eval_name)
    if sub_eval_name:
        parts.append(sub_eval_name)
    if attempt_num:
        parts.append(f"attempt_{attempt_num}")
    if template_name:
        parts.append(template_name)
    return "_".join(parts)


def with_filelock() -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            output_dir = kwargs.get("output_dir")
            if output_dir is None:
                output_dir = next(
                    (
                        arg
                        for arg_name, arg in zip(func.__code__.co_varnames, args)
                        if arg_name == "output_dir"
                    ),
                    None,
                )
            if not output_dir:
                raise ValueError("Lock path argument output_dir is required.")

            with FileLock(get_results_csv_path(output_dir) + ".lock"):
                return func(*args, **kwargs)

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
            return False
        return True


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
    step_desc_prompt_tokens: int = 0,
    step_desc_completion_tokens: int = 0,
    step_desc_total_tokens: int = 0,
    step_desc_api_cost: float = 0.0,
    step_desc_model_name: str = "",
    step_desc_model_provider: str = "",
    final_decision_prompt_tokens: int = 0,
    final_decision_completion_tokens: int = 0,
    final_decision_total_tokens: int = 0,
    final_decision_api_cost: float = 0.0,
    final_decision_model_name: str = "",
    final_decision_model_provider: str = "",
    failure_step: int | None = None,
) -> pd.DataFrame:
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
    df.loc[task_id, f"{prefix}_evaluation"] = result_map.get(success, "E")
    df.loc[task_id, f"{prefix}_details"] = str(evaluation_detail)
    df.loc[task_id, f"{prefix}_evaluation_method"] = evaluation_method

    df.loc[task_id, f"{prefix}_step_desc_prompt_tokens"] = step_desc_prompt_tokens
    df.loc[task_id, f"{prefix}_step_desc_completion_tokens"] = step_desc_completion_tokens
    df.loc[task_id, f"{prefix}_step_desc_total_tokens"] = step_desc_total_tokens
    df.loc[task_id, f"{prefix}_step_desc_api_cost"] = step_desc_api_cost
    df.loc[task_id, f"{prefix}_step_desc_model_name"] = step_desc_model_name
    df.loc[task_id, f"{prefix}_step_desc_model_provider"] = step_desc_model_provider

    df.loc[task_id, f"{prefix}_final_decision_prompt_tokens"] = final_decision_prompt_tokens
    df.loc[task_id, f"{prefix}_final_decision_completion_tokens"] = (
        final_decision_completion_tokens
    )
    df.loc[task_id, f"{prefix}_final_decision_total_tokens"] = final_decision_total_tokens
    df.loc[task_id, f"{prefix}_final_decision_api_cost"] = final_decision_api_cost
    df.loc[task_id, f"{prefix}_final_decision_model_name"] = final_decision_model_name
    df.loc[task_id, f"{prefix}_final_decision_model_provider"] = (
        final_decision_model_provider
    )
    df.loc[task_id, f"{prefix}_failure_step"] = (
        failure_step if failure_step is not None else ""
    )

    df.reset_index(inplace=True)
    try_save_csv(df, get_results_csv_path(output_dir))
    return df


@with_filelock()
def save_badcase_result(
    output_dir: str,
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
    output_dir: str,
    task_identifier: str,
    agent: str,
    attempt_num: int,
    reasoning_mode: str,
    action_mode: str,
    irr_percentage: float | int | None,
    irr_total_units: Any,
    irr_correct_units: Any,
    irr_reason: str,
    irr_method: str,
) -> pd.DataFrame:
    df = pd.read_csv(get_results_csv_path(output_dir))
    df.set_index("task_identifier", inplace=True)

    prefix = get_col_name_from_template(
        "",
        agent_name=agent,
        eval_name=reasoning_mode,
        sub_eval_name=action_mode,
        attempt_num=attempt_num,
    )

    df.loc[task_identifier, f"{prefix}_irr_percentage"] = (
        irr_percentage if irr_percentage is not None else ""
    )
    df.loc[task_identifier, f"{prefix}_irr_total_units"] = str(irr_total_units)
    df.loc[task_identifier, f"{prefix}_irr_correct_units"] = str(irr_correct_units)
    df.loc[task_identifier, f"{prefix}_irr_reason"] = (
        irr_reason[:500] if irr_reason else ""
    )
    df.loc[task_identifier, f"{prefix}_irr_method"] = irr_method

    df.reset_index(inplace=True)
    try_save_csv(df, get_results_csv_path(output_dir))
    return df
