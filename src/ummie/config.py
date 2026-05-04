import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


CONFIG_PATH_ENV_VAR = "UMMIE_CONFIG"
GAME_ENV_VAR = "UMMIE_GAME"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "ummie" / "config.toml"


@dataclass(frozen=True)
class GameConfig:
    env_var: str
    default_mods_dir: str
    game_dir: str | None = None


@dataclass(frozen=True)
class Config:
    games: dict[str, GameConfig]
    default_game: str = "wrath"


_DEFAULT_GAMES: dict[str, GameConfig] = {
    "wrath": GameConfig(
        env_var="WRATH_MODS_DIR",
        default_mods_dir="/Applications/Pathfinder Wrath of the Righteous/Mods",
    ),
    "rogue-trader": GameConfig(
        env_var="ROGUE_TRADER_MODS_DIR",
        default_mods_dir=str(
            Path.home()
            / "Library"
            / "Application Support"
            / "com.Owlcat-Games.Warhammer-40000-Rogue-Trader"
            / "UnityModManager"
        ),
        game_dir="/Applications/Warhammer 40,000 Rogue Trader/WH40KRT.app",
    ),
}

DEFAULT_CONFIG = Config(games=_DEFAULT_GAMES)


def load_config(config_path: Path | None = None) -> Config:
    """Load config from a TOML file, falling back to built-in defaults if absent."""
    resolved = _resolve_config_path(config_path)
    if not resolved.exists():
        return DEFAULT_CONFIG
    with open(resolved, "rb") as f:
        data = tomllib.load(f)
    games_raw = data.get("games", {})
    games = (
        {name: _parse_game_config(cfg) for name, cfg in games_raw.items()}
        if games_raw
        else dict(_DEFAULT_GAMES)
    )
    return Config(games=games, default_game=data.get("default_game", "wrath"))


def resolve_game(game_arg: str | None, config: Config) -> str:
    """Resolve the active game: CLI arg > UMMIE_GAME env var > config default."""
    if game_arg is not None:
        return game_arg
    from_env = os.getenv(GAME_ENV_VAR)
    if from_env is not None:
        if from_env not in config.games:
            raise SystemExit(
                f"Error: unknown game {from_env!r} in {GAME_ENV_VAR}.\n"
                f"Valid games: {', '.join(config.games)}"
            )
        return from_env
    return config.default_game


def _resolve_config_path(config_path: Path | None) -> Path:
    if config_path is not None:
        return config_path
    env_path = os.getenv(CONFIG_PATH_ENV_VAR)
    return Path(env_path) if env_path else DEFAULT_CONFIG_PATH


def _parse_game_config(data: dict) -> GameConfig:
    return GameConfig(
        env_var=data["env_var"],
        default_mods_dir=data["default_mods_dir"],
        game_dir=data.get("game_dir"),
    )
