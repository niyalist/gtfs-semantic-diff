"""config/default.toml の読み込み。全閾値はここ経由で参照する (コード内リテラル禁止)。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# src レイアウト前提: config.py → gtfs_semdiff → src → リポジトリルート
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "default.toml"

ENV_CONFIG_PATH = "GTFS_SEMDIFF_CONFIG"


@dataclass
class Config:
    raw: dict[str, Any]
    source_path: Path

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """設定を読み込む。優先順: 引数 > 環境変数 GTFS_SEMDIFF_CONFIG > 同梱 default.toml。"""
        if path is None:
            path = os.environ.get(ENV_CONFIG_PATH) or DEFAULT_CONFIG_PATH
        path = Path(path).expanduser()
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        return cls(raw=raw, source_path=path)

    def get(self, *keys: str, default: Any = None) -> Any:
        """ドット階層をキー列で辿る。例: cfg.get("identity", "stop_clustering", "intra_generation_radius_m")"""
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def repository_base_url(self) -> str:
        return self.get("repository", "base_url", default="https://api.gtfs-data.jp/v2")

    @property
    def cache_dir(self) -> Path:
        return Path(self.get("repository", "cache_dir", default="~/.cache/gtfs-semdiff")).expanduser()
