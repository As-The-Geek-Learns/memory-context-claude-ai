"""Configuration management for Cortex.

Handles loading, saving, and resolving paths for the Cortex data directory.
All configuration has sensible defaults — Cortex works out of the box
without any config file. User overrides are stored in ~/.cortex/config.json.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _default_cortex_home() -> Path:
    """Return the default Cortex home directory (~/.cortex)."""
    return Path.home() / ".cortex"


def _validate_cortex_home(path_value: str | Path) -> Path:
    """Validate cortex_home from config: must be under ~/.cortex.

    Prevents path traversal or arbitrary directory use. If path_value
    resolves outside Path.home() / '.cortex', returns the default.
    """
    if not path_value:
        return _default_cortex_home()
    try:
        resolved = Path(path_value).resolve()
        allowed_root = Path.home() / ".cortex"
        if resolved.is_relative_to(allowed_root):
            return resolved
    except (OSError, RuntimeError):
        pass
    return _default_cortex_home()


@dataclass
class CortexConfig:
    """Configuration for the Cortex memory system.

    All values have defaults that match the research paper's recommendations.
    Values are tunable per the calibration plan in paper §11.4.
    """

    # WHAT: Root directory for all Cortex data.
    # WHY: Centralized global storage with per-project isolation.
    cortex_home: Path = field(default_factory=_default_cortex_home)

    # Decay and salience parameters (paper §9.4)
    decay_rate: float = 0.995
    confidence_threshold: float = 0.5
    reinforcement_multiplier: float = 1.2

    # Briefing budget (paper §9.5)
    max_briefing_tokens: int = 3000
    max_full_decisions: int = 50
    max_summary_decisions: int = 30

    # Decision tiering thresholds (paper §9.4 — immortal event growth management)
    decision_active_sessions: int = 20
    decision_aging_sessions: int = 50

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        data = asdict(self)
        data["cortex_home"] = str(self.cortex_home)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CortexConfig":
        """Deserialize from a dictionary, with defaults for missing keys."""
        defaults = cls()
        return cls(
            cortex_home=_validate_cortex_home(data.get("cortex_home", str(defaults.cortex_home))),
            decay_rate=data.get("decay_rate", defaults.decay_rate),
            confidence_threshold=data.get("confidence_threshold", defaults.confidence_threshold),
            reinforcement_multiplier=data.get("reinforcement_multiplier", defaults.reinforcement_multiplier),
            max_briefing_tokens=data.get("max_briefing_tokens", defaults.max_briefing_tokens),
            max_full_decisions=data.get("max_full_decisions", defaults.max_full_decisions),
            max_summary_decisions=data.get("max_summary_decisions", defaults.max_summary_decisions),
            decision_active_sessions=data.get("decision_active_sessions", defaults.decision_active_sessions),
            decision_aging_sessions=data.get("decision_aging_sessions", defaults.decision_aging_sessions),
        )


def get_cortex_home(config: CortexConfig | None = None) -> Path:
    """Return the Cortex home directory, creating it if needed.

    Args:
        config: Optional config override. Uses default if not provided.

    Returns:
        Path to ~/.cortex/ (or configured override).
    """
    home = config.cortex_home if config else _default_cortex_home()
    home.mkdir(parents=True, exist_ok=True)
    return home


def get_project_dir(project_hash: str, config: CortexConfig | None = None) -> Path:
    """Return the project-specific data directory, creating it if needed.

    Args:
        project_hash: 16-character hex hash identifying the project.
        config: Optional config override.

    Returns:
        Path to ~/.cortex/projects/<hash>/
    """
    home = get_cortex_home(config)
    project_dir = home / "projects" / project_hash
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def get_config_path(config: CortexConfig | None = None) -> Path:
    """Return the path to the global config file."""
    home = config.cortex_home if config else _default_cortex_home()
    return home / "config.json"


def load_config(cortex_home: Path | None = None) -> CortexConfig:
    """Load configuration from ~/.cortex/config.json.

    Returns default config if the file doesn't exist or is invalid.
    This is intentionally lenient — Cortex should always start.

    Args:
        cortex_home: Override the cortex home directory.
                     Useful for testing with tmp directories.
    """
    if cortex_home is not None:
        config_path = cortex_home / "config.json"
    else:
        config_path = _default_cortex_home() / "config.json"

    if not config_path.exists():
        config = CortexConfig()
        if cortex_home is not None:
            config.cortex_home = cortex_home
        return config

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        config = CortexConfig.from_dict(data)
        if cortex_home is not None:
            config.cortex_home = cortex_home
        return config
    except (json.JSONDecodeError, OSError):
        # WHAT: Return defaults if config is corrupted or unreadable.
        # WHY: Cortex should never fail to start due to bad config.
        config = CortexConfig()
        if cortex_home is not None:
            config.cortex_home = cortex_home
        return config


def save_config(config: CortexConfig) -> None:
    """Save configuration to ~/.cortex/config.json.

    Creates the directory structure if needed. Uses atomic write
    (temp file + rename) for crash safety.
    """
    config.cortex_home.mkdir(parents=True, exist_ok=True)
    config_path = config.cortex_home / "config.json"
    tmp_path = config_path.with_suffix(".json.tmp")

    try:
        content = json.dumps(config.to_dict(), indent=2)
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.rename(config_path)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
