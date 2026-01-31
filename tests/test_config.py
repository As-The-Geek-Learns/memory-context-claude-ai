"""Tests for the Cortex configuration system."""

import json
from pathlib import Path

from memory_context_claude_ai.config import (
    CortexConfig,
    get_config_path,
    get_cortex_home,
    get_project_dir,
    load_config,
    save_config,
)


class TestCortexConfigDefaults:
    """Tests for CortexConfig default values."""

    def test_default_cortex_home(self) -> None:
        """Default cortex_home is ~/.cortex."""
        config = CortexConfig()
        assert config.cortex_home == Path.home() / ".cortex"

    def test_default_decay_rate(self) -> None:
        """Default decay rate is 0.995 per hour."""
        config = CortexConfig()
        assert config.decay_rate == 0.995

    def test_default_confidence_threshold(self) -> None:
        """Default confidence threshold is 0.5."""
        config = CortexConfig()
        assert config.confidence_threshold == 0.5

    def test_default_reinforcement_multiplier(self) -> None:
        """Default reinforcement multiplier is 1.2."""
        config = CortexConfig()
        assert config.reinforcement_multiplier == 1.2

    def test_default_briefing_budget(self) -> None:
        """Default max briefing tokens is 3000."""
        config = CortexConfig()
        assert config.max_briefing_tokens == 3000

    def test_default_decision_limits(self) -> None:
        """Default decision limits match paper §9.4."""
        config = CortexConfig()
        assert config.max_full_decisions == 50
        assert config.max_summary_decisions == 30

    def test_default_decision_tiering(self) -> None:
        """Default tiering thresholds for immortal event management."""
        config = CortexConfig()
        assert config.decision_active_sessions == 20
        assert config.decision_aging_sessions == 50


class TestCortexConfigSerialization:
    """Tests for CortexConfig.to_dict() and from_dict()."""

    def test_to_dict_converts_path_to_string(self) -> None:
        """to_dict converts cortex_home Path to string."""
        config = CortexConfig(cortex_home=Path("/tmp/test"))
        data = config.to_dict()
        assert data["cortex_home"] == "/tmp/test"
        assert isinstance(data["cortex_home"], str)

    def test_round_trip(self, tmp_path: Path) -> None:
        """Serializing then deserializing preserves all values."""
        original = CortexConfig(
            cortex_home=tmp_path / ".cortex",
            decay_rate=0.99,
            confidence_threshold=0.6,
            reinforcement_multiplier=1.5,
            max_briefing_tokens=5000,
            max_full_decisions=100,
            max_summary_decisions=50,
            decision_active_sessions=30,
            decision_aging_sessions=60,
        )
        data = original.to_dict()
        restored = CortexConfig.from_dict(data)

        assert restored.cortex_home == original.cortex_home
        assert restored.decay_rate == original.decay_rate
        assert restored.confidence_threshold == original.confidence_threshold
        assert restored.reinforcement_multiplier == original.reinforcement_multiplier
        assert restored.max_briefing_tokens == original.max_briefing_tokens
        assert restored.max_full_decisions == original.max_full_decisions
        assert restored.max_summary_decisions == original.max_summary_decisions
        assert restored.decision_active_sessions == original.decision_active_sessions
        assert restored.decision_aging_sessions == original.decision_aging_sessions

    def test_from_dict_uses_defaults_for_missing_keys(self) -> None:
        """from_dict fills in defaults for any missing keys."""
        config = CortexConfig.from_dict({})
        defaults = CortexConfig()
        assert config.decay_rate == defaults.decay_rate
        assert config.confidence_threshold == defaults.confidence_threshold
        assert config.max_briefing_tokens == defaults.max_briefing_tokens

    def test_from_dict_partial_data(self) -> None:
        """from_dict handles partial dictionaries gracefully."""
        config = CortexConfig.from_dict({"decay_rate": 0.99})
        assert config.decay_rate == 0.99
        assert config.confidence_threshold == 0.5  # default


class TestGetCortexHome:
    """Tests for get_cortex_home()."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        """get_cortex_home creates the directory if it doesn't exist."""
        cortex_home = tmp_path / ".cortex"
        config = CortexConfig(cortex_home=cortex_home)
        result = get_cortex_home(config)
        assert result == cortex_home
        assert cortex_home.is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        """Calling get_cortex_home twice doesn't error."""
        cortex_home = tmp_path / ".cortex"
        config = CortexConfig(cortex_home=cortex_home)
        get_cortex_home(config)
        get_cortex_home(config)
        assert cortex_home.is_dir()


class TestGetProjectDir:
    """Tests for get_project_dir()."""

    def test_creates_project_directory(self, tmp_cortex_home: Path, sample_config: CortexConfig) -> None:
        """get_project_dir creates the project directory."""
        project_dir = get_project_dir("abc123def456abcd", sample_config)
        assert project_dir.is_dir()
        assert project_dir.name == "abc123def456abcd"
        assert project_dir.parent.name == "projects"

    def test_nested_structure(self, tmp_cortex_home: Path, sample_config: CortexConfig) -> None:
        """Project dir is at ~/.cortex/projects/<hash>/."""
        project_dir = get_project_dir("abc123def456abcd", sample_config)
        assert project_dir == tmp_cortex_home / "projects" / "abc123def456abcd"


class TestGetConfigPath:
    """Tests for get_config_path()."""

    def test_returns_config_json_path(self, tmp_cortex_home: Path, sample_config: CortexConfig) -> None:
        """Config path is ~/.cortex/config.json."""
        config_path = get_config_path(sample_config)
        assert config_path == tmp_cortex_home / "config.json"


class TestLoadConfig:
    """Tests for load_config()."""

    def test_returns_defaults_when_no_file(self, tmp_path: Path) -> None:
        """Returns default config when config.json doesn't exist."""
        cortex_home = tmp_path / ".cortex"
        cortex_home.mkdir()
        config = load_config(cortex_home)
        assert config.decay_rate == 0.995
        assert config.cortex_home == cortex_home

    def test_loads_from_file(self, tmp_path: Path) -> None:
        """Loads config values from an existing config.json."""
        cortex_home = tmp_path / ".cortex"
        cortex_home.mkdir()
        config_path = cortex_home / "config.json"
        config_path.write_text(json.dumps({
            "decay_rate": 0.99,
            "max_briefing_tokens": 5000,
        }))

        config = load_config(cortex_home)
        assert config.decay_rate == 0.99
        assert config.max_briefing_tokens == 5000
        assert config.cortex_home == cortex_home

    def test_handles_corrupted_json(self, tmp_path: Path) -> None:
        """Returns defaults if config.json is corrupted."""
        cortex_home = tmp_path / ".cortex"
        cortex_home.mkdir()
        config_path = cortex_home / "config.json"
        config_path.write_text("{not valid json")

        config = load_config(cortex_home)
        assert config.decay_rate == 0.995  # default
        assert config.cortex_home == cortex_home

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Returns defaults if config.json is empty."""
        cortex_home = tmp_path / ".cortex"
        cortex_home.mkdir()
        config_path = cortex_home / "config.json"
        config_path.write_text("")

        config = load_config(cortex_home)
        assert config.decay_rate == 0.995


class TestSaveConfig:
    """Tests for save_config()."""

    def test_creates_config_file(self, tmp_path: Path) -> None:
        """save_config creates a valid JSON file."""
        cortex_home = tmp_path / ".cortex"
        config = CortexConfig(cortex_home=cortex_home)
        save_config(config)

        config_path = cortex_home / "config.json"
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert data["decay_rate"] == 0.995
        assert data["cortex_home"] == str(cortex_home)

    def test_round_trip_through_file(self, tmp_path: Path) -> None:
        """Save then load produces equivalent config."""
        cortex_home = tmp_path / ".cortex"
        original = CortexConfig(
            cortex_home=cortex_home,
            decay_rate=0.99,
            max_briefing_tokens=4000,
        )
        save_config(original)
        loaded = load_config(cortex_home)

        assert loaded.decay_rate == original.decay_rate
        assert loaded.max_briefing_tokens == original.max_briefing_tokens

    def test_atomic_write(self, tmp_path: Path) -> None:
        """save_config uses atomic write (no .tmp file left over)."""
        cortex_home = tmp_path / ".cortex"
        config = CortexConfig(cortex_home=cortex_home)
        save_config(config)

        tmp_file = cortex_home / "config.json.tmp"
        assert not tmp_file.exists()
        assert (cortex_home / "config.json").exists()
