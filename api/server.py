from __future__ import annotations

import json
import hmac
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).resolve().with_name("config.json")
ENGINE_API_CONFIG_NAME = "config.api.toml"

LEVELS: dict[int, dict[str, Any]] = {
    1: {
        "level": 1,
        "name": "beginner",
        "turnTimeMs": 100,
        "matchTimeMs": 300000,
        "maxDepth": 3,
        "maxNodes": 10000,
        "strength": 10,
        "cautionFactor": 0,
        "threadNum": 1,
    },
    2: {
        "level": 2,
        "name": "casual",
        "turnTimeMs": 300,
        "matchTimeMs": 300000,
        "maxDepth": 5,
        "maxNodes": 50000,
        "strength": 30,
        "cautionFactor": 1,
        "threadNum": 1,
    },
    3: {
        "level": 3,
        "name": "standard",
        "turnTimeMs": 800,
        "matchTimeMs": 300000,
        "maxDepth": 8,
        "maxNodes": 300000,
        "strength": 60,
        "cautionFactor": 3,
        "threadNum": 1,
    },
    4: {
        "level": 4,
        "name": "strong",
        "turnTimeMs": 2000,
        "matchTimeMs": 300000,
        "maxDepth": 10,
        "maxNodes": 1000000,
        "strength": 85,
        "cautionFactor": 3,
        "threadNum": 1,
    },
    5: {
        "level": 5,
        "name": "deep",
        "turnTimeMs": 5000,
        "matchTimeMs": 300000,
        "maxDepth": 14,
        "maxNodes": 5000000,
        "strength": 100,
        "cautionFactor": 4,
        "threadNum": 1,
    },
}

RULE_VALUES = {
    "freestyle": 0,
    "standard": 1,
    "renju": 2,
    "swap": 3,
    "soosorv": 5,
    "swap2": 6,
}

COLORS = {"black", "white"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


class EngineError(Exception):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def read_json_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)
    env_map = {
        "RAPFI_HOST": ("host", str),
        "RAPFI_PORT": ("port", int),
        "RAPFI_IDLE_SLEEP_SECONDS": ("idleSleepSeconds", int),
        "RAPFI_MAX_ACTIVE_ENGINES": ("maxActiveEngines", int),
        "RAPFI_ENGINE_DIR": ("engineDir", str),
        "RAPFI_ENGINE_EXE": ("engineExe", str),
        "RAPFI_STORAGE_DIR": ("storageDir", str),
        "RAPFI_DEFAULT_BOARD_SIZE": ("defaultBoardSize", int),
        "RAPFI_DEFAULT_RULE": ("defaultRule", str),
        "RAPFI_DEFAULT_AI_COLOR": ("defaultAiColor", str),
        "RAPFI_DEFAULT_LEVEL": ("defaultLevel", int),
        "RAPFI_API_KEY": ("apiKey", str),
    }
    for env_name, (key, caster) in env_map.items():
        value = os.environ.get(env_name)
        if value not in (None, ""):
            config[key] = caster(value)
    return config


def level_settings(level: int) -> dict[str, Any]:
    if level not in LEVELS:
        raise ApiError(400, "invalid_level", "level must be an integer from 1 to 5")
    return dict(LEVELS[level])


def normalize_rule(rule: str | None) -> str:
    if not rule:
        return "freestyle"
    value = str(rule).strip().lower()
    if value not in RULE_VALUES:
        raise ApiError(400, "invalid_rule", f"unsupported rule: {rule}")
    return value


def other_color(color: str) -> str:
    return "white" if color == "black" else "black"


def normalize_color(color: str | None, *, allow_none: bool = False) -> str | None:
    if color is None:
        if allow_none:
            return None
        raise ApiError(400, "missing_color", "color is required")
    value = str(color).strip().lower()
    aliases = {
        "b": "black",
        "black": "black",
        "hei": "black",
        "h": "black",
        "黑": "black",
        "黑棋": "black",
        "w": "white",
        "white": "white",
        "bai": "white",
        "白": "white",
        "白棋": "white",
    }
    value = aliases.get(value, value)
    if value == "none" and allow_none:
        return None
    if value not in COLORS:
        raise ApiError(400, "invalid_color", "color must be black or white")
    return value


def xy_to_coord(x: int, y: int) -> str:
    return f"{chr(ord('A') + x)}{y + 1}"


def coord_to_xy(value: str, board_size: int) -> tuple[int, int]:
    text = str(value).strip().upper()
    pair = re.match(r"^(\d{1,2})\s*,\s*(\d{1,2})$", text)
    if pair:
        x = int(pair.group(1))
        y = int(pair.group(2))
    else:
        match = re.match(r"^([A-Z])(\d{1,2})$", text)
        if not match:
            raise ApiError(400, "invalid_coord", "coord must look like H8 or 7,7")
        x = ord(match.group(1)) - ord("A")
        y = int(match.group(2)) - 1
    if x < 0 or y < 0 or x >= board_size or y >= board_size:
        raise ApiError(400, "coord_out_of_range", "coord is outside the board")
    return x, y


def body_xy(body: dict[str, Any], board_size: int) -> tuple[int, int]:
    if "coord" in body:
        return coord_to_xy(str(body["coord"]), board_size)
    if "x" in body and "y" in body:
        try:
            x = int(body["x"])
            y = int(body["y"])
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "invalid_coord", "x and y must be integers") from exc
        if x < 0 or y < 0 or x >= board_size or y >= board_size:
            raise ApiError(400, "coord_out_of_range", "coord is outside the board")
        return x, y
    raise ApiError(400, "missing_coord", "provide coord or x/y")


@dataclass
class Move:
    color: str
    x: int
    y: int
    source: str = "user"
    at: str = field(default_factory=now_iso)

    @property
    def coord(self) -> str:
        return xy_to_coord(self.x, self.y)

    def to_dict(self) -> dict[str, Any]:
        return {
            "color": self.color,
            "coord": self.coord,
            "x": self.x,
            "y": self.y,
            "source": self.source,
            "at": self.at,
        }


@dataclass
class Game:
    id: str
    board_size: int
    rule: str
    ai_color: str | None
    settings: dict[str, Any]
    created_at: str
    updated_at: str
    last_access_at: str
    status: str = "sleeping"
    moves: list[Move] = field(default_factory=list)
    winner: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def turn(self) -> str:
        return "black" if len(self.moves) % 2 == 0 else "white"

    def occupied(self) -> dict[tuple[int, int], Move]:
        return {(m.x, m.y): m for m in self.moves}

    def to_dict(self, *, include_moves: bool = True) -> dict[str, Any]:
        data = {
            "id": self.id,
            "status": self.status,
            "boardSize": self.board_size,
            "rule": self.rule,
            "aiColor": self.ai_color,
            "turn": self.turn if not self.winner else None,
            "winner": self.winner,
            "moveCount": len(self.moves),
            "settings": dict(self.settings),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "lastAccessAt": self.last_access_at,
        }
        if include_moves:
            data["moves"] = [m.to_dict() for m in self.moves]
        return data


def merge_settings(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    settings = dict(base)
    if "level" in patch:
        try:
            settings = level_settings(int(patch["level"]))
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "invalid_level", "level must be an integer from 1 to 5") from exc
    numeric_fields = {
        "turnTimeMs": (10, 600000),
        "matchTimeMs": (1000, 86400000),
        "maxDepth": (2, 200),
        "maxNodes": (1, 10000000000),
        "strength": (0, 100),
        "cautionFactor": (0, 4),
        "threadNum": (1, 256),
    }
    for key, (low, high) in numeric_fields.items():
        if key in patch:
            try:
                value = int(patch[key])
            except (TypeError, ValueError) as exc:
                raise ApiError(400, "invalid_setting", f"{key} must be an integer") from exc
            if value < low or value > high:
                raise ApiError(400, "invalid_setting", f"{key} must be in [{low}, {high}]")
            settings[key] = value
    settings["level"] = int(settings.get("level", 3))
    settings.setdefault("name", LEVELS.get(settings["level"], LEVELS[3])["name"])
    return settings


def detect_winner(moves: list[Move], board_size: int) -> str | None:
    if not moves:
        return None
    board = {(m.x, m.y): m.color for m in moves}
    last = moves[-1]
    directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
    for dx, dy in directions:
        total = 1
        for sign in (1, -1):
            x = last.x + dx * sign
            y = last.y + dy * sign
            while 0 <= x < board_size and 0 <= y < board_size and board.get((x, y)) == last.color:
                total += 1
                x += dx * sign
                y += dy * sign
        if total >= 5:
            return last.color
    if len(moves) >= board_size * board_size:
        return "draw"
    return None


def ensure_engine_config(engine_dir: Path) -> Path:
    source = engine_dir / "config.toml"
    target = engine_dir / ENGINE_API_CONFIG_NAME
    if not source.exists():
        raise ApiError(500, "missing_engine_config", f"missing {source}")
    content = source.read_text(encoding="utf-8")
    content = re.sub(
        r'coord_conversion_mode\s*=\s*"[^"]+"',
        'coord_conversion_mode = "none"',
        content,
    )
    content = re.sub(
        r"default_thread_num\s*=\s*\d+",
        "default_thread_num = 1",
        content,
    )
    content = re.sub(
        r'message_mode\s*=\s*"[^"]+"',
        'message_mode = "normal"',
        content,
    )
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
    return target


class RapfiEngine:
    def __init__(self, engine_exe: Path, engine_dir: Path, board_size: int, rule: str):
        self.engine_exe = engine_exe
        self.engine_dir = engine_dir
        self.config_path = ensure_engine_config(engine_dir)
        self.board_size = board_size
        self.rule = rule
        self.process: subprocess.Popen[str] | None = None
        self.output: queue.Queue[str] = queue.Queue()
        self.lock = threading.RLock()
        self.reader: threading.Thread | None = None
        self.last_applied: dict[str, Any] | None = None

    def start(self) -> None:
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(
                [str(self.engine_exe), f"--config={self.config_path.name}"],
                cwd=str(self.engine_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            self.reader = threading.Thread(target=self._read_output, daemon=True)
            self.reader.start()
            self._send(f"START {self.board_size}")
            line, lines = self._read_until(lambda text: text == "OK" or text.startswith("ERROR"), 20)
            if line != "OK":
                raise EngineError("engine start failed: " + " | ".join(lines))

    def _read_output(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.output.put(line.rstrip("\r\n"))

    def _send(self, command: str) -> None:
        if not self.process or self.process.poll() is not None:
            raise EngineError("engine process is not running")
        assert self.process.stdin is not None
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def _read_until(self, predicate: Any, timeout: float) -> tuple[str | None, list[str]]:
        deadline = time.time() + timeout
        lines: list[str] = []
        while time.time() < deadline:
            try:
                line = self.output.get(timeout=0.1)
            except queue.Empty:
                continue
            stripped = line.strip()
            lines.append(stripped)
            if predicate(stripped):
                return stripped, lines
        return None, lines

    def _drain(self, wait: float = 0.05) -> list[str]:
        time.sleep(wait)
        lines: list[str] = []
        while True:
            try:
                lines.append(self.output.get_nowait().strip())
            except queue.Empty:
                break
        return lines

    def apply_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.start()
            rule_value = RULE_VALUES.get(self.rule, 0)
            commands = [
                f"INFO rule {rule_value}",
                f"INFO timeout_turn {int(settings['turnTimeMs'])}",
                f"INFO timeout_match {int(settings['matchTimeMs'])}",
                f"INFO max_depth {int(settings['maxDepth'])}",
                f"INFO max_node {int(settings['maxNodes'])}",
                f"INFO caution_factor {int(settings['cautionFactor'])}",
                f"INFO strength {int(settings['strength'])}",
                f"INFO thread_num {int(settings['threadNum'])}",
            ]
            for command in commands:
                self._send(command)
            output = self._drain(0.12)
            errors = [line for line in output if line.startswith("ERROR")]
            if errors:
                raise EngineError("settings rejected: " + " | ".join(errors))
            self.last_applied = {
                "at": now_iso(),
                "pid": self.process.pid if self.process else None,
                "settings": dict(settings),
                "commands": commands,
                "output": output,
            }
            return dict(self.last_applied)

    def compute_move(self, moves: list[Move], settings: dict[str, Any]) -> Move:
        with self.lock:
            self.start()
            self.apply_settings(settings)
            self._drain(0.01)
            self._send("BOARD")
            for move in moves:
                color_value = 1 if move.color == "black" else 2
                self._send(f"{move.x},{move.y},{color_value}")
            self._send("DONE")
            timeout = max(15.0, float(settings["turnTimeMs"]) / 1000.0 + 12.0)
            line, lines = self._read_until(self._is_move_or_error, timeout)
            if line is None:
                raise EngineError("engine move timeout: " + " | ".join(lines[-8:]))
            if line.startswith("ERROR"):
                raise EngineError("engine error: " + " | ".join(lines[-8:]))
            x, y = self._parse_engine_move(line)
            if x < 0 or y < 0 or x >= self.board_size or y >= self.board_size:
                raise EngineError(f"engine returned out-of-range move: {line}")
            color = "black" if len(moves) % 2 == 0 else "white"
            return Move(color=color, x=x, y=y, source="ai")

    @staticmethod
    def _is_move_or_error(text: str) -> bool:
        if text.startswith("ERROR"):
            return True
        return re.match(r"^\s*-?\d+\s*,\s*-?\d+\s*$", text) is not None

    @staticmethod
    def _parse_engine_move(text: str) -> tuple[int, int]:
        match = re.match(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*$", text)
        if not match:
            raise EngineError(f"invalid engine move: {text}")
        return int(match.group(1)), int(match.group(2))

    def close(self) -> None:
        with self.lock:
            if not self.process:
                return
            if self.process.poll() is None:
                try:
                    self._send("END")
                    self.process.wait(timeout=1.0)
                except Exception:
                    self.process.kill()
            self.process = None


class GameStore:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def path(self, game_id: str) -> Path:
        return self.storage_dir / f"{game_id}.txt"

    def save(self, game: Game) -> None:
        game.updated_at = now_iso()
        game.winner = detect_winner(game.moves, game.board_size)
        lines = [
            "# rapfi-api-game v1",
            f"id: {game.id}",
            f"board_size: {game.board_size}",
            f"rule: {game.rule}",
            f"ai_color: {game.ai_color or 'none'}",
            f"status: {game.status}",
            f"created_at: {game.created_at}",
            f"updated_at: {game.updated_at}",
            f"last_access_at: {game.last_access_at}",
            f"winner: {game.winner or 'none'}",
            "settings_json: " + json.dumps(game.settings, ensure_ascii=False, separators=(",", ":")),
            "",
            "moves:",
        ]
        for index, move in enumerate(game.moves, 1):
            lines.append(f"{index} {move.color} {move.coord} {move.x} {move.y} {move.source} {move.at}")
        text = "\n".join(lines) + "\n"
        tmp = self.path(game.id).with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path(game.id))

    def load_all(self) -> dict[str, Game]:
        games: dict[str, Game] = {}
        for path in self.storage_dir.glob("game-*.txt"):
            game = self.load(path)
            games[game.id] = game
        return games

    def load(self, path: Path) -> Game:
        meta: dict[str, str] = {}
        moves: list[Move] = []
        in_moves = False
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line == "moves:":
                in_moves = True
                continue
            if not in_moves:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            _, color, _coord, x, y, source, at = parts[:7]
            moves.append(Move(color=color, x=int(x), y=int(y), source=source, at=at))

        settings = json.loads(meta.get("settings_json", "{}"))
        if not settings:
            settings = level_settings(3)
        game = Game(
            id=meta["id"],
            board_size=int(meta["board_size"]),
            rule=normalize_rule(meta.get("rule")),
            ai_color=None if meta.get("ai_color") == "none" else normalize_color(meta.get("ai_color"), allow_none=True),
            settings=settings,
            created_at=meta.get("created_at", now_iso()),
            updated_at=meta.get("updated_at", now_iso()),
            last_access_at=meta.get("last_access_at", now_iso()),
            status="sleeping",
            moves=moves,
            winner=None if meta.get("winner") in (None, "none") else meta.get("winner"),
        )
        game.winner = detect_winner(game.moves, game.board_size)
        return game

    def delete(self, game_id: str) -> None:
        self.path(game_id).unlink(missing_ok=True)


class GameManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.engine_dir = resolve_path(config["engineDir"])
        self.engine_exe = resolve_path(config["engineExe"])
        self.idle_sleep_seconds = int(config.get("idleSleepSeconds", 300))
        self.max_active_engines = int(config.get("maxActiveEngines", 3))
        self.store = GameStore(resolve_path(config["storageDir"]))
        self.games = self.store.load_all()
        self.engines: dict[str, RapfiEngine] = {}
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.monitor = threading.Thread(target=self._idle_monitor, daemon=True)
        self.monitor.start()

    def create_game(self, body: dict[str, Any]) -> dict[str, Any]:
        board_size = int(body.get("boardSize", self.config.get("defaultBoardSize", 15)))
        if board_size < 5 or board_size > 22:
            raise ApiError(400, "invalid_board_size", "boardSize must be in [5, 22]")
        rule = normalize_rule(body.get("rule", self.config.get("defaultRule", "freestyle")))
        ai_color = normalize_color(body.get("aiColor", self.config.get("defaultAiColor", "white")), allow_none=True)
        level = int(body.get("level", self.config.get("defaultLevel", 2)))
        settings = merge_settings(level_settings(level), body.get("settings", {}))
        game_id = body.get("id") or self._new_game_id()
        if not re.match(r"^game-[A-Za-z0-9_.-]+$", game_id):
            raise ApiError(400, "invalid_game_id", "game id must start with game- and use safe characters")
        with self.lock:
            if game_id in self.games:
                raise ApiError(409, "game_exists", "game id already exists")
            now = now_iso()
            game = Game(
                id=game_id,
                board_size=board_size,
                rule=rule,
                ai_color=ai_color,
                settings=settings,
                created_at=now,
                updated_at=now,
                last_access_at=now,
                status="sleeping",
            )
            self.games[game_id] = game
            self.store.save(game)

        ai_move = None
        if ai_color == "black" and body.get("autoAi", True):
            ai_move = self._ai_move(game).to_dict()
        return {"ok": True, "game": game.to_dict(), "aiMove": ai_move}

    def get_game(self, game_id: str) -> Game:
        with self.lock:
            game = self.games.get(game_id)
        if not game:
            raise ApiError(404, "game_not_found", "game not found")
        return game

    def list_games(self) -> dict[str, Any]:
        with self.lock:
            games = [game.to_dict(include_moves=False) for game in sorted(self.games.values(), key=lambda g: g.updated_at, reverse=True)]
        return {"ok": True, "games": games}

    def get_game_response(self, game_id: str) -> dict[str, Any]:
        game = self.get_game(game_id)
        self._touch(game)
        return {"ok": True, "game": game.to_dict()}

    def delete_game(self, game_id: str) -> dict[str, Any]:
        game = self.get_game(game_id)
        with game.lock:
            self.sleep_game(game_id)
            with self.lock:
                self.games.pop(game_id, None)
            self.store.delete(game_id)
        return {"ok": True, "gameId": game_id, "deleted": True}

    def add_move(self, game_id: str, body: dict[str, Any]) -> dict[str, Any]:
        game = self.get_game(game_id)
        auto_ai = bool(body.get("autoAi", True))
        with game.lock:
            self._touch(game)
            if game.winner:
                raise ApiError(409, "game_finished", "game already has a winner")
            color = normalize_color(body.get("color"), allow_none=True) or game.turn
            if color != game.turn:
                raise ApiError(409, "wrong_turn", f"expected {game.turn}")
            x, y = body_xy(body, game.board_size)
            move = self._append_move_locked(game, color, x, y, "user")
            ai_move = None
            if auto_ai and not game.winner and game.ai_color == game.turn:
                ai_move = self._ai_move_locked(game)
            self.store.save(game)
            return {
                "ok": True,
                "game": game.to_dict(),
                "move": move.to_dict(),
                "aiMove": ai_move.to_dict() if ai_move else None,
            }

    def ai_move(self, game_id: str) -> dict[str, Any]:
        game = self.get_game(game_id)
        with game.lock:
            self._touch(game)
            move = self._ai_move_locked(game)
            self.store.save(game)
            return {"ok": True, "game": game.to_dict(), "aiMove": move.to_dict()}

    def undo(self, game_id: str, body: dict[str, Any]) -> dict[str, Any]:
        game = self.get_game(game_id)
        plies = int(body.get("plies", body.get("steps", 1)))
        if plies < 1:
            raise ApiError(400, "invalid_plies", "plies must be >= 1")
        with game.lock:
            self._touch(game)
            removed = game.moves[-plies:]
            del game.moves[-plies:]
            game.winner = detect_winner(game.moves, game.board_size)
            self.store.save(game)
            return {
                "ok": True,
                "game": game.to_dict(),
                "removed": [move.to_dict() for move in removed],
            }

    def patch_settings(self, game_id: str, body: dict[str, Any]) -> dict[str, Any]:
        game = self.get_game(game_id)
        with game.lock:
            self._touch(game)
            game.settings = merge_settings(game.settings, body)
            applied = False
            engine_applied = None
            engine = self.engines.get(game.id)
            if engine:
                try:
                    engine_applied = engine.apply_settings(game.settings)
                    applied = True
                except EngineError as exc:
                    raise ApiError(500, "engine_settings_failed", str(exc)) from exc
            self.store.save(game)
            return {
                "ok": True,
                "gameId": game.id,
                "settings": dict(game.settings),
                "applied": applied,
                "willApplyOnWake": not applied,
                "engineApplied": engine_applied,
            }

    def sleep_game(self, game_id: str) -> dict[str, Any]:
        game = self.get_game(game_id)
        with game.lock:
            self._sleep_game_locked(game)
            self.store.save(game)
            return {"ok": True, "game": game.to_dict()}

    def wake_game(self, game_id: str) -> dict[str, Any]:
        game = self.get_game(game_id)
        with game.lock:
            self._touch(game)
            engine = self._ensure_engine(game)
            applied = engine.apply_settings(game.settings)
            self.store.save(game)
            return {"ok": True, "game": game.to_dict(), "engineApplied": applied}

    def text_command(self, body: dict[str, Any] | str) -> dict[str, Any]:
        text = body if isinstance(body, str) else str(body.get("text", ""))
        text = text.strip()
        if not text:
            raise ApiError(400, "empty_text", "text is empty")
        lower = text.lower()
        if "新" in text or "new" in lower:
            level_match = re.search(r"(?:level|lv|强度|档)\s*[:= ]?\s*([1-5])", text, re.I)
            level = int(level_match.group(1)) if level_match else int(self.config.get("defaultLevel", 2))
            ai_color = "white"
            if "ai黑" in text or "ai执黑" in text or "ai black" in lower:
                ai_color = "black"
            if "ai无" in text or "no ai" in lower:
                ai_color = None
            response = self.create_game({"level": level, "aiColor": ai_color})
            response["action"] = "create_game"
            return response
        game_match = re.search(r"(game-[A-Za-z0-9_.-]+)", text)
        if not game_match:
            raise ApiError(400, "missing_game_id", "text command must include a game id")
        game_id = game_match.group(1)
        if any(token in lower for token in ["ai", "think", "next"]) or any(token in text for token in ["继续", "下一步", "思考"]):
            response = self.ai_move(game_id)
            response["action"] = "ai_move"
            return response
        coord_match = re.search(r"\b([A-Za-z]\d{1,2}|\d{1,2}\s*,\s*\d{1,2})\b", text)
        if not coord_match:
            raise ApiError(400, "missing_coord", "text command must include a coord")
        color = None
        if "黑" in text or re.search(r"\bblack\b|\bb\b", lower):
            color = "black"
        if "白" in text or re.search(r"\bwhite\b|\bw\b", lower):
            color = "white"
        response = self.add_move(game_id, {"coord": coord_match.group(1), "color": color})
        response["action"] = "move"
        return response

    def shutdown(self) -> None:
        self.stopping.set()
        with self.lock:
            engines = list(self.engines.values())
            self.engines.clear()
        for engine in engines:
            engine.close()

    def _new_game_id(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"game-{stamp}-{uuid.uuid4().hex[:6]}"

    def _touch(self, game: Game) -> None:
        game.last_access_at = now_iso()

    def _append_move_locked(self, game: Game, color: str, x: int, y: int, source: str) -> Move:
        if (x, y) in game.occupied():
            raise ApiError(409, "occupied", "coord is already occupied")
        move = Move(color=color, x=x, y=y, source=source)
        game.moves.append(move)
        game.winner = detect_winner(game.moves, game.board_size)
        return move

    def _ai_move(self, game: Game) -> Move:
        with game.lock:
            return self._ai_move_locked(game)

    def _ai_move_locked(self, game: Game) -> Move:
        if game.winner:
            raise ApiError(409, "game_finished", "game already has a winner")
        engine = self._ensure_engine(game)
        try:
            move = engine.compute_move(list(game.moves), game.settings)
        except EngineError as exc:
            raise ApiError(500, "engine_failed", str(exc)) from exc
        if (move.x, move.y) in game.occupied():
            raise ApiError(500, "engine_invalid_move", "engine returned an occupied coord")
        move.color = game.turn
        game.moves.append(move)
        game.winner = detect_winner(game.moves, game.board_size)
        self.store.save(game)
        return move

    def _ensure_engine(self, game: Game) -> RapfiEngine:
        with self.lock:
            engine = self.engines.get(game.id)
            if engine:
                game.status = "active"
                return engine
            self._make_capacity_locked(exclude_game_id=game.id)
            engine = RapfiEngine(self.engine_exe, self.engine_dir, game.board_size, game.rule)
            self.engines[game.id] = engine
            game.status = "active"
            return engine

    def _make_capacity_locked(self, exclude_game_id: str) -> None:
        if len(self.engines) < self.max_active_engines:
            return
        candidates = [
            self.games[gid]
            for gid in self.engines
            if gid != exclude_game_id and gid in self.games
        ]
        if not candidates:
            raise ApiError(503, "engine_capacity", "max active engines reached")
        candidates.sort(key=lambda item: item.last_access_at)
        self._sleep_game_locked(candidates[0])

    def _sleep_game_locked(self, game: Game) -> None:
        with self.lock:
            engine = self.engines.pop(game.id, None)
        if engine:
            engine.close()
        game.status = "sleeping"

    def _idle_monitor(self) -> None:
        while not self.stopping.wait(10):
            now = time.time()
            with self.lock:
                active_ids = list(self.engines.keys())
            for game_id in active_ids:
                game = self.games.get(game_id)
                if not game:
                    continue
                try:
                    last = datetime.fromisoformat(game.last_access_at).timestamp()
                except ValueError:
                    last = now
                if now - last >= self.idle_sleep_seconds:
                    locked = game.lock.acquire(blocking=False)
                    if not locked:
                        continue
                    try:
                        self._sleep_game_locked(game)
                        self.store.save(game)
                    finally:
                        game.lock.release()


class ApiHandler(BaseHTTPRequestHandler):
    manager: GameManager
    api_key: str = ""

    def do_OPTIONS(self) -> None:
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _handle(self, method: str) -> None:
        try:
            if not self._is_public_route(method) and not self._is_authorized():
                raise ApiError(401, "unauthorized", "missing or invalid API key")
            result = self._route(method)
            self._send_json(200, result)
        except ApiError as exc:
            payload = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
            if exc.details is not None:
                payload["error"]["details"] = exc.details
            self._send_json(exc.status, payload)
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": {"code": "internal_error", "message": str(exc)}})

    def _route(self, method: str) -> dict[str, Any]:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        body = self._read_body()

        if method == "GET" and parts == ["health"]:
            return {"ok": True, "status": "up", "time": now_iso()}
        if method == "GET" and parts == ["levels"]:
            return {"ok": True, "levels": [dict(LEVELS[i]) for i in sorted(LEVELS)]}
        if method == "GET" and parts == ["games"]:
            return self.manager.list_games()
        if method == "POST" and parts == ["games"]:
            return self.manager.create_game(body)
        if method == "POST" and parts == ["text"]:
            return self.manager.text_command(body)

        if len(parts) >= 2 and parts[0] == "games":
            game_id = parts[1]
            if method == "GET" and len(parts) == 2:
                return self.manager.get_game_response(game_id)
            if method == "DELETE" and len(parts) == 2:
                return self.manager.delete_game(game_id)
            if method == "POST" and len(parts) == 3 and parts[2] == "move":
                return self.manager.add_move(game_id, body)
            if method == "POST" and len(parts) == 3 and parts[2] == "ai-move":
                return self.manager.ai_move(game_id)
            if method == "POST" and len(parts) == 3 and parts[2] == "undo":
                return self.manager.undo(game_id, body)
            if method == "POST" and len(parts) == 3 and parts[2] == "sleep":
                return self.manager.sleep_game(game_id)
            if method == "POST" and len(parts) == 3 and parts[2] == "wake":
                return self.manager.wake_game(game_id)
            if method == "PATCH" and len(parts) == 3 and parts[2] == "settings":
                return self.manager.patch_settings(game_id, body)

        raise ApiError(404, "not_found", "route not found")

    def _is_public_route(self, method: str) -> bool:
        if method == "OPTIONS":
            return True
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        return method == "GET" and parts == ["health"]

    def _is_authorized(self) -> bool:
        expected = self.api_key.strip()
        if not expected:
            return True
        candidates = []
        api_key = self.headers.get("X-API-Key", "").strip()
        if api_key:
            candidates.append(api_key)
        authorization = self.headers.get("Authorization", "").strip()
        if authorization.lower().startswith("bearer "):
            candidates.append(authorization[7:].strip())
        elif authorization:
            candidates.append(authorization)
        return any(hmac.compare_digest(candidate, expected) for candidate in candidates)

    def _read_body(self) -> dict[str, Any] | str:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("text/plain"):
            return raw
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError(400, "invalid_json", "request body must be valid JSON") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "invalid_json", "request JSON must be an object")
        return data

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
        if status == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="rapfi-api"')
        self.end_headers()
        self.wfile.write(data)


class RapfiApiServer(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    config = read_json_config()
    manager = GameManager(config)
    ApiHandler.manager = manager
    ApiHandler.api_key = str(config.get("apiKey", "") or "")
    host = config.get("host", "127.0.0.1")
    port = int(config.get("port", 8787))
    server = RapfiApiServer((host, port), ApiHandler)
    print(f"Rapfi API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        manager.shutdown()


if __name__ == "__main__":
    main()
