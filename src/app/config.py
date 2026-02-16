"""Configuration loading for raw-deduplicator_v2."""

import dataclasses
from pathlib import Path
from typing import Any, cast

import yaml


@dataclasses.dataclass(frozen=True)
class ScannerConfig:
    """Configuration for the file scanner.

    Attributes:
        paths: List of absolute directory paths to scan.
        extensions: List of file extensions with dots (e.g., [".jpg", ".raw"]).
        case_sensitive: Whether extension matching is case sensitive.
        recursive: Whether to crawl subdirectories.
        skip_dirs: List of directory names to skip during traversal.
        database: Path to the SQLite database file.
    """

    paths: list[str]
    extensions: list[str]
    case_sensitive: bool
    recursive: bool
    skip_dirs: list[str]
    database: str


def load_config(config_path: Path) -> ScannerConfig:
    """Load and validate scanner configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        A validated ScannerConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        KeyError: If a required key is missing from the config.
        TypeError: If a config value has the wrong type.
        ValueError: If a config value is invalid.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw: Any = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise TypeError(f"Expected YAML root to be a mapping, got {type(raw).__name__}")

    data: dict[str, Any] = cast(dict[str, Any], raw)

    _validate_required_keys(data)
    _validate_types(data)
    _validate_values(data)

    paths: list[str] = [str(p) for p in data["paths"]]
    extensions: list[str] = [str(e) for e in data["extensions"]]
    skip_dirs: list[str] = [str(d) for d in data["skip_dirs"]]

    return ScannerConfig(
        paths=paths,
        extensions=extensions,
        case_sensitive=data["case_sensitive"],
        recursive=data["recursive"],
        skip_dirs=skip_dirs,
        database=str(data["database"]),
    )


_REQUIRED_KEYS: list[str] = ["paths", "extensions", "case_sensitive", "recursive", "skip_dirs", "database"]


def _validate_required_keys(data: dict[str, Any]) -> None:
    """Validate that all required keys are present in the config.

    Args:
        data: The parsed YAML dictionary.

    Raises:
        KeyError: If a required key is missing.
    """
    for key in _REQUIRED_KEYS:
        if key not in data:
            raise KeyError(f"Missing required config key: '{key}'")


def _validate_types(data: dict[str, Any]) -> None:
    """Validate that config values have the correct types.

    Args:
        data: The parsed YAML dictionary with all required keys present.

    Raises:
        TypeError: If any value has the wrong type.
    """
    if not isinstance(data["paths"], list):
        raise TypeError(f"'paths' must be a list, got {type(data['paths']).__name__}")
    if not isinstance(data["extensions"], list):
        raise TypeError(f"'extensions' must be a list, got {type(data['extensions']).__name__}")
    if not isinstance(data["case_sensitive"], bool):
        raise TypeError(f"'case_sensitive' must be a bool, got {type(data['case_sensitive']).__name__}")
    if not isinstance(data["recursive"], bool):
        raise TypeError(f"'recursive' must be a bool, got {type(data['recursive']).__name__}")
    if not isinstance(data["skip_dirs"], list):
        raise TypeError(f"'skip_dirs' must be a list, got {type(data['skip_dirs']).__name__}")
    if not isinstance(data["database"], str):
        raise TypeError(f"'database' must be a string, got {type(data['database']).__name__}")


def _validate_values(data: dict[str, Any]) -> None:
    """Validate that config values are semantically valid.

    Args:
        data: The parsed YAML dictionary with all required keys and correct types.

    Raises:
        ValueError: If any value is invalid.
        TypeError: If a list element has the wrong type.
    """
    if len(data["paths"]) == 0:
        raise ValueError("'paths' must not be empty")
    if len(data["extensions"]) == 0:
        raise ValueError("'extensions' must not be empty")
    if len(data["database"]) == 0:
        raise ValueError("'database' must not be empty")

    _validate_string_list(data["paths"], "path")
    _validate_extensions(data["extensions"])
    _validate_string_list(data["skip_dirs"], "skip_dir")


def _validate_string_list(items: list[Any], label: str) -> None:
    """Validate that all items in a list are strings.

    Args:
        items: The list to validate.
        label: A human-readable label for error messages.

    Raises:
        TypeError: If any item is not a string.
    """
    for item in items:
        if not isinstance(item, str):
            raise TypeError(f"Each {label} must be a string, got {type(item).__name__}")


def _validate_extensions(extensions: list[Any]) -> None:
    """Validate that all extensions are strings starting with a dot.

    Args:
        extensions: The list of extensions to validate.

    Raises:
        TypeError: If any extension is not a string.
        ValueError: If any extension does not start with a dot.
    """
    for ext in extensions:
        if not isinstance(ext, str):
            raise TypeError(f"Each extension must be a string, got {type(ext).__name__}")
        if not ext.startswith("."):
            raise ValueError(f"Extension must start with '.', got '{ext}'")
