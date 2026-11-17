import re
from pathlib import Path

import pytest

from app.config import ConfigError, Settings, load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_defaults_work_without_any_environment(tmp_path):
    s = load_settings(env={}, dotenv_path=tmp_path / "none.env")
    assert s.professor_github_ids == ()
    assert s.mail_rate_per_sec == 8
    assert s.database_path.name == "app.db"


def test_environment_overrides_defaults(tmp_path):
    s = load_settings(
        env={"PROFESSOR_GITHUB_IDS": "101, 202", "MAIL_RATE_PER_SEC": "5"},
        dotenv_path=tmp_path / "none.env",
    )
    assert s.professor_github_ids == (101, 202)
    assert s.mail_rate_per_sec == 5


def test_dotenv_file_is_read_and_environment_wins(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text('# comment\nBASE_URL="http://localhost:8000"\nMAIL_FROM=a@b.c\n')
    s = load_settings(env={"MAIL_FROM": "env@b.c"}, dotenv_path=dotenv)
    assert s.base_url == "http://localhost:8000"
    assert s.mail_from == "env@b.c"


def test_non_numeric_github_id_gives_clear_error(tmp_path):
    with pytest.raises(ConfigError) as err:
        load_settings(env={"PROFESSOR_GITHUB_IDS": "abc"}, dotenv_path=tmp_path / "x")
    assert "PROFESSOR_GITHUB_IDS" in str(err.value)


def test_env_example_lists_every_setting_with_no_values():
    text = (REPO_ROOT / ".env.example").read_text()
    keys = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))
    assert keys == set(Settings.env_names())
    for line in text.splitlines():
        if re.match(r"^[A-Z][A-Z0-9_]*=", line):
            assert line.split("=", 1)[1].strip() == "", f"값이 들어 있다: {line}"


def test_env_example_copied_as_is_loads_with_defaults(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text((REPO_ROOT / ".env.example").read_text())
    s = load_settings(env={}, dotenv_path=dotenv)
    assert s == load_settings(env={}, dotenv_path=tmp_path / "none.env")
