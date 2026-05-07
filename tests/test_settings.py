from ai_agent.settings import Settings, T212Env


def test_defaults_safe_for_dev() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.t212_env is T212Env.demo
    assert s.run_mode.value == "dry_run"
    assert s.llm_daily_cost_cap_usd == 3.0
    assert s.llm_daily_cost_alert_usd < s.llm_daily_cost_cap_usd


def test_t212_base_url_demo() -> None:
    s = Settings(_env_file=None, t212_env=T212Env.demo)  # type: ignore[call-arg]
    assert "demo" in s.t212_base_url


def test_t212_base_url_live() -> None:
    s = Settings(_env_file=None, t212_env=T212Env.live)  # type: ignore[call-arg]
    assert "live" in s.t212_base_url
