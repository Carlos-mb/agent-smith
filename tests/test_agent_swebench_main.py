import agent_swebench


def test_ctrl_c_ends_with_a_short_message_and_no_traceback(tmp_path, monkeypatch, capsys):
    task = tmp_path / "task.json"
    task.write_text(
        '{"instance_id": "demo__demo-1", "problem_statement": "p", '
        '"docker_image": "demo:latest", "eval_script": "echo"}'
    )
    output = tmp_path / "solution.json"

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(agent_swebench, "run_swebench_agent", interrupted)

    assert agent_swebench.main([
        "--task-file", str(task), "--output", str(output),
        "--model-name", "m", "--provider-url", "http://localhost",
    ]) == 130
    assert capsys.readouterr().err.strip() == "Interrupted: no solution file was written."
    assert not output.exists()
