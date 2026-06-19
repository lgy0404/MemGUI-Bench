import csv
import json

from mobile_world.core.leaderboard_export import save_leaderboard_outputs


def _write_attempt_traj(root, task_name: str, attempt: int, steps: int) -> None:
    if attempt == 1:
        task_dir = root / task_name
    else:
        task_dir = root / "_attempt_trajs" / task_name / f"attempt_{attempt}"
    task_dir.mkdir(parents=True, exist_ok=True)
    task_dir.joinpath("traj.json").write_text(
        json.dumps(
            {
                "0": {
                    "traj": [
                        {
                            "step": index + 1,
                            "task_goal": f"Goal for {task_name}",
                            "prediction": "ok",
                            "action": {"action_type": "wait"},
                        }
                        for index in range(steps)
                    ],
                    "token_usage": {
                        "prompt_tokens": steps * 100,
                        "completion_tokens": steps * 10,
                    },
                }
            }
        )
    )


def test_save_leaderboard_outputs_from_existing_results(tmp_path):
    task_names = [
        "005-SearchSportsScores",
        "021-NavigateAndComparePrices",
        "113-CrossAppCarAnalysisAndReporting",
    ]
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "suite_family": "memgui_bench",
                "pass_at_k": 3,
                "task_list": task_names,
                "task_count": len(task_names),
                "run_status": "completed",
            }
        )
    )

    _write_attempt_traj(tmp_path, task_names[0], 1, 2)
    _write_attempt_traj(tmp_path, task_names[1], 1, 3)
    _write_attempt_traj(tmp_path, task_names[1], 2, 4)
    _write_attempt_traj(tmp_path, task_names[2], 1, 5)
    _write_attempt_traj(tmp_path, task_names[2], 2, 6)
    _write_attempt_traj(tmp_path, task_names[2], 3, 7)

    eval_root = tmp_path / "_memgui_eval"
    eval_root.mkdir()
    fieldnames = [
        "task_identifier",
        "task_description",
        "task_app",
        "num_apps",
        "is_cross_app",
        "category",
        "requires_ui_memory",
        "shortcut_potential",
        "output_type",
        "golden_steps",
        "task_difficulty",
        "task_language",
        "general_e2e_direct_with_action_attempt_1_evaluation",
        "general_e2e_direct_with_action_attempt_1_irr_percentage",
        "general_e2e_direct_with_action_attempt_2_evaluation",
        "general_e2e_direct_with_action_attempt_3_evaluation",
    ]
    with (eval_root / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "task_identifier": task_names[0],
                "num_apps": "1",
                "requires_ui_memory": "N",
                "golden_steps": "8",
                "task_difficulty": "1",
                "general_e2e_direct_with_action_attempt_1_evaluation": "S",
            }
        )
        writer.writerow(
            {
                "task_identifier": task_names[1],
                "num_apps": "1",
                "requires_ui_memory": "Y",
                "golden_steps": "36",
                "task_difficulty": "2",
                "general_e2e_direct_with_action_attempt_1_evaluation": "F",
                "general_e2e_direct_with_action_attempt_1_irr_percentage": "40",
                "general_e2e_direct_with_action_attempt_2_evaluation": "S",
            }
        )
        writer.writerow(
            {
                "task_identifier": task_names[2],
                "num_apps": "3",
                "requires_ui_memory": "Y",
                "golden_steps": "60",
                "task_difficulty": "3",
                "general_e2e_direct_with_action_attempt_1_evaluation": "F",
                "general_e2e_direct_with_action_attempt_1_irr_percentage": "60",
                "general_e2e_direct_with_action_attempt_2_evaluation": "F",
                "general_e2e_direct_with_action_attempt_3_evaluation": "F",
            }
        )

    exported = save_leaderboard_outputs(str(tmp_path), max_attempts=3, trigger="test")

    assert exported is not None
    metrics, leaderboard_path = exported
    assert metrics["pass_at_1_rate"] == 100 / 3
    assert metrics["pass_at_3_rate"] == 200 / 3
    assert metrics["avg_irr"] == 50.0
    assert metrics["frr"] == 50.0
    assert metrics["mtpr"] == 0.0

    leaderboard = json.loads((tmp_path / "general-e2e.json").read_text())
    assert leaderboard_path.endswith("general-e2e.json")
    assert leaderboard["name"] == "general_e2e"
    assert leaderboard["backbone"] == "-"
    assert leaderboard["avg"] == {"p1": 33.3, "p3": 66.7}
    assert leaderboard["crossApp"]["app1"] == {"p1": 50.0, "p3": 100.0, "irr": 40.0}
    assert leaderboard["crossApp"]["app3"] == {"p1": 0.0, "p3": 0.0, "irr": 60.0}
    assert leaderboard["difficulty"]["medium"] == {"p1": 0.0, "p3": 100.0, "irr": 40.0}
    assert leaderboard["metrics"]["shortTerm"]["irr"] == 50.0
    assert leaderboard["metrics"]["longTerm"]["frr"] == 50.0
    assert (tmp_path / "metrics_summary.json").exists()
    assert (tmp_path / "metrics_summary.csv").exists()
    assert (tmp_path / "metrics_history.jsonl").exists()
