"""Configuration manager based on SQLite persistence."""

from __future__ import annotations

import importlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from app.console_utils import safe_print as print
from app.i18n import t
from app.runtime_paths import default_db_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_SETTINGS_DB = default_db_path("settings.db")


class ConfigManager:
    """Configuration manager (SQLite persistence)."""

    def __init__(self, env_file: str = str(DEFAULT_ENV_FILE), db_file: str = str(DEFAULT_SETTINGS_DB)):
        env_path = Path(env_file)
        db_path = Path(db_file)
        self.env_file = env_path if env_path.is_absolute() else Path(env_file).resolve()
        self.db_file = db_path if db_path.is_absolute() else Path(db_file).resolve()
        self.db_file.parent.mkdir(parents=True, exist_ok=True)

        self.default_config = {
            "AI_API_KEY": {
                "value": "",
                "description": t("AI API key (OpenRouter/OpenAI compatible)"),
                "required": True,
                "type": "password",
            },
            "AI_API_BASE_URL": {
                "value": "https://openrouter.ai/api/v1",
                "description": t("AI API base URL (OpenAI compatible)"),
                "required": False,
                "type": "text",
            },
            "DEFAULT_MODEL_NAME": {
                "value": "deepseek/deepseek-v3.2",
                "description": t("Default model name (OpenAI-compatible)"),
                "required": False,
                "type": "select",
            },
            "TUSHARE_TOKEN": {
                "value": "",
                "description": t("Tushare token (optional)"),
                "required": False,
                "type": "password",
            },
            "MINIQMT_ENABLED": {
                "value": "false",
                "description": t("Enable MiniQMT trading"),
                "required": False,
                "type": "boolean",
            },
            "MINIQMT_ACCOUNT_ID": {
                "value": "",
                "description": t("MiniQMT account ID"),
                "required": False,
                "type": "text",
            },
            "MINIQMT_HOST": {
                "value": "127.0.0.1",
                "description": t("MiniQMT host"),
                "required": False,
                "type": "text",
            },
            "MINIQMT_PORT": {
                "value": "58610",
                "description": t("MiniQMT port"),
                "required": False,
                "type": "text",
            },
            "EMAIL_ENABLED": {
                "value": "false",
                "description": t("Enable email notifications"),
                "required": False,
                "type": "boolean",
            },
            "SMTP_SERVER": {
                "value": "",
                "description": t("SMTP server"),
                "required": False,
                "type": "text",
            },
            "SMTP_PORT": {
                "value": "587",
                "description": t("SMTP port"),
                "required": False,
                "type": "text",
            },
            "EMAIL_FROM": {
                "value": "",
                "description": t("Sender email"),
                "required": False,
                "type": "text",
            },
            "EMAIL_PASSWORD": {
                "value": "",
                "description": t("Email authorization code"),
                "required": False,
                "type": "password",
            },
            "EMAIL_TO": {
                "value": "",
                "description": t("Recipient email"),
                "required": False,
                "type": "text",
            },
            "WEBHOOK_ENABLED": {
                "value": "false",
                "description": t("Enable webhook notifications"),
                "required": False,
                "type": "boolean",
            },
            "WEBHOOK_TYPE": {
                "value": "dingtalk",
                "description": t("Webhook type (dingtalk/feishu)"),
                "required": False,
                "type": "select",
                "options": ["dingtalk", "feishu"],
            },
            "WEBHOOK_URL": {
                "value": "",
                "description": t("Webhook URL"),
                "required": False,
                "type": "text",
            },
            "WEBHOOK_KEYWORD": {
                "value": "aiagents-notify",
                "description": t("Webhook custom keyword (for DingTalk security check)"),
                "required": False,
                "type": "text",
            },
        }

        self._init_db()
        self._bootstrap_from_env_once()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_file))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _parse_env_file(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        if not self.env_file.exists():
            return values
        try:
            with open(self.env_file, "r", encoding="utf-8") as file:
                for raw in file:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    values[key] = value
        except Exception as exc:
            print(t("Failed to read .env: {error}", error=exc))
        return values

    @staticmethod
    def _normalize_model_name(model_name: str | None, base_url: str | None) -> str:
        normalized = (model_name or "").strip()
        if not normalized:
            return ""
        base = (base_url or "").lower()
        if "openrouter.ai" in base:
            if normalized.lower() == "deepseek-chat":
                return "deepseek/deepseek-chat"
            if normalized.lower() == "deepseek-reasoner":
                return "deepseek/deepseek-reasoner"
        return normalized

    def _upsert_many(self, values: Dict[str, str]) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    """
                    INSERT INTO system_settings(key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, str(value), now),
                )
            conn.commit()

    def _read_db_values(self) -> Dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def _bootstrap_from_env_once(self) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(1) AS c FROM system_settings").fetchone()
            count = int(row["c"]) if row else 0
        if count > 0:
            return

        env_values = self._parse_env_file()
        seed: Dict[str, str] = {}
        for key, meta in self.default_config.items():
            seed[key] = str(env_values.get(key, meta["value"]))

        seed["DEFAULT_MODEL_NAME"] = self._normalize_model_name(
            seed.get("DEFAULT_MODEL_NAME"),
            seed.get("AI_API_BASE_URL"),
        ) or "deepseek/deepseek-v3.2"
        self._upsert_many(seed)

    def read_env(self) -> Dict[str, str]:
        """Read settings (legacy method name, source is SQLite)."""
        config = self._read_db_values()
        for key, meta in self.default_config.items():
            if key not in config:
                config[key] = str(meta["value"])
        config["DEFAULT_MODEL_NAME"] = self._normalize_model_name(
            config.get("DEFAULT_MODEL_NAME"),
            config.get("AI_API_BASE_URL"),
        ) or "deepseek/deepseek-v3.2"
        return config

    def write_env(self, config: Dict[str, str]) -> bool:
        """Persist settings (legacy method name, writes to SQLite)."""
        try:
            current = self.read_env()
            merged = {key: current.get(key, str(meta["value"])) for key, meta in self.default_config.items()}
            for key, value in config.items():
                if key in merged:
                    merged[key] = "" if value is None else str(value)

            merged["DEFAULT_MODEL_NAME"] = self._normalize_model_name(
                merged.get("DEFAULT_MODEL_NAME"),
                merged.get("AI_API_BASE_URL"),
            ) or "deepseek/deepseek-v3.2"
            self._upsert_many(merged)
            return True
        except Exception as exc:
            print(t("Failed to save settings: {error}", error=exc))
            return False

    def get_config_info(self) -> Dict[str, Dict[str, Any]]:
        """Return settings metadata (description/type/options)."""
        current_values = self.read_env()
        config_info: Dict[str, Dict[str, Any]] = {}
        for key, info in self.default_config.items():
            config_info[key] = {
                "value": current_values.get(key, info["value"]),
                "description": info["description"],
                "required": info["required"],
                "type": info["type"],
            }
            if "options" in info:
                config_info[key]["options"] = info["options"]

        model_cfg = config_info.get("DEFAULT_MODEL_NAME")
        if model_cfg is not None:
            model_cfg["type"] = "select"
            try:
                from app import model_config

                model_cfg["options"] = list(model_config.model_options.keys())
            except Exception as exc:
                print(t("Failed to load model options: {error}", error=exc))
                fallback = [model_cfg.get("value") or "deepseek/deepseek-v3.2", "deepseek/deepseek-reasoner"]
                model_cfg["options"] = list(dict.fromkeys([str(item) for item in fallback if item]))
        return config_info

    def validate_config(self, config: Dict[str, str]) -> tuple[bool, str]:
        """Validate settings."""
        for key, info in self.default_config.items():
            if info["required"] and not config.get(key):
                return False, t("Required field {field} cannot be empty", field=info["description"])

        api_key = config.get("AI_API_KEY", "")
        if api_key and len(api_key) < 20:
            return False, t("AI API key format is invalid (too short)")
        return True, t("Configuration validated")

    def reload_config(self):
        """Write settings to runtime env and hot-reload app.config."""
        values = self.read_env()
        for key, value in values.items():
            os.environ[key] = "" if value is None else str(value)
        try:
            import app.config as app_config

            importlib.reload(app_config)
        except Exception:
            pass


# Global singleton
config_manager = ConfigManager()

