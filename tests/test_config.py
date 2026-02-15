"""Tests for the config module."""

import pytest
import yaml

from raw_deduplicator_v2.config import ScannerConfig, load_config


class TestLoadConfigSuccess:
    def test_loads_valid_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp/test"],
                    "extensions": [".jpg", ".png"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [".git"],
                    "database": "data/files.db",
                }
            )
        )

        config = load_config(config_file)

        assert isinstance(config, ScannerConfig)
        assert config.paths == ["/tmp/test"]
        assert config.extensions == [".jpg", ".png"]
        assert config.case_sensitive is False
        assert config.recursive is True
        assert config.skip_dirs == [".git"]
        assert config.database == "data/files.db"

    def test_loads_config_with_empty_skip_dirs(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp/test"],
                    "extensions": [".jpg"],
                    "case_sensitive": True,
                    "recursive": False,
                    "skip_dirs": [],
                    "database": "out.db",
                }
            )
        )

        config = load_config(config_file)

        assert config.skip_dirs == []

    def test_loads_config_with_multiple_paths(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp/a", "/tmp/b"],
                    "extensions": [".jpg"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [],
                    "database": "out.db",
                }
            )
        )

        config = load_config(config_file)

        assert config.paths == ["/tmp/a", "/tmp/b"]


class TestLoadConfigMissingFile:
    def test_raises_file_not_found(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(missing)


class TestLoadConfigMissingKeys:
    @pytest.mark.parametrize(
        "missing_key",
        [
            "paths",
            "extensions",
            "case_sensitive",
            "recursive",
            "skip_dirs",
            "database",
        ],
    )
    def test_raises_key_error_for_missing_key(self, tmp_path, missing_key):
        data = {
            "paths": ["/tmp"],
            "extensions": [".jpg"],
            "case_sensitive": False,
            "recursive": True,
            "skip_dirs": [],
            "database": "out.db",
        }
        del data[missing_key]

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(data))

        with pytest.raises(KeyError, match=missing_key):
            load_config(config_file)


class TestLoadConfigInvalidTypes:
    def test_paths_not_a_list(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": "/tmp",
                    "extensions": [".jpg"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [],
                    "database": "out.db",
                }
            )
        )

        with pytest.raises(TypeError, match="'paths' must be a list"):
            load_config(config_file)

    def test_case_sensitive_not_a_bool(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp"],
                    "extensions": [".jpg"],
                    "case_sensitive": "yes",
                    "recursive": True,
                    "skip_dirs": [],
                    "database": "out.db",
                }
            )
        )

        with pytest.raises(TypeError, match="'case_sensitive' must be a bool"):
            load_config(config_file)

    def test_database_not_a_string(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp"],
                    "extensions": [".jpg"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [],
                    "database": 123,
                }
            )
        )

        with pytest.raises(TypeError, match="'database' must be a string"):
            load_config(config_file)

    def test_yaml_root_not_a_dict(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("- item1\n- item2\n")

        with pytest.raises(TypeError, match="Expected YAML root to be a mapping"):
            load_config(config_file)


class TestLoadConfigInvalidValues:
    def test_empty_paths(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": [],
                    "extensions": [".jpg"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [],
                    "database": "out.db",
                }
            )
        )

        with pytest.raises(ValueError, match="'paths' must not be empty"):
            load_config(config_file)

    def test_empty_extensions(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp"],
                    "extensions": [],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [],
                    "database": "out.db",
                }
            )
        )

        with pytest.raises(ValueError, match="'extensions' must not be empty"):
            load_config(config_file)

    def test_extension_without_dot(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp"],
                    "extensions": ["jpg"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [],
                    "database": "out.db",
                }
            )
        )

        with pytest.raises(ValueError, match="Extension must start with '.'"):
            load_config(config_file)

    def test_empty_database(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "paths": ["/tmp"],
                    "extensions": [".jpg"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [],
                    "database": "",
                }
            )
        )

        with pytest.raises(ValueError, match="'database' must not be empty"):
            load_config(config_file)

    def test_non_string_extension(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        raw_yaml = "paths:\n  - /tmp\nextensions:\n  - 123\ncase_sensitive: false\nrecursive: true\nskip_dirs: []\ndatabase: out.db\n"
        config_file.write_text(raw_yaml)

        with pytest.raises(TypeError, match="Each extension must be a string"):
            load_config(config_file)
