from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class User:
    id: int
    username: str
    auth_token: str


@dataclass(frozen=True)
class DebtRecord:
    id: int
    borrower_id: int
    lender_id: int
    amount: float
    description: str
    status: str
    created_at: str
    borrower_username: str | None = None
    lender_username: str | None = None


@dataclass(frozen=True)
class LaundryRecord:
    id: int
    user_id: int
    vruntime: float
    weight: float
    status: str
    username: str | None = None


@dataclass(frozen=True)
class BarterRecord:
    id: int
    user_id: int
    has_skill_id: int
    wants_skill_id: int
    username: str | None = None


class DormiXRepository:
    """SQLite repository for DormiX's normalized data model."""

    def __init__(self, db_path: str | Path = "dormix.db") -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.initialize_schema()

    def close(self) -> None:
        self.conn.close()

    def initialize_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                auth_token TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                borrower_id INTEGER NOT NULL,
                lender_id INTEGER NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (borrower_id) REFERENCES users(id),
                FOREIGN KEY (lender_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS laundry_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                vruntime REAL NOT NULL DEFAULT 0,
                weight REAL NOT NULL DEFAULT 1 CHECK (weight > 0),
                status TEXT NOT NULL DEFAULT 'waiting',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS barter_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                has_skill_id INTEGER NOT NULL,
                wants_skill_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS trip_pools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_name TEXT NOT NULL,
                total_budget REAL NOT NULL CHECK (total_budget >= 0),
                status TEXT NOT NULL DEFAULT 'planned'
            );
            """
        )
        self.conn.commit()

    def create_user(self, username: str, auth_token: str) -> User:
        username = self._normalize_username(username)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO users (username, auth_token) VALUES (?, ?)",
                (username, auth_token.strip()),
            )
        return User(id=cur.lastrowid, username=username, auth_token=auth_token.strip())

    def get_user_by_username(self, username: str) -> User | None:
        row = self.conn.execute(
            "SELECT id, username, auth_token FROM users WHERE username = ?",
            (self._normalize_username(username),),
        ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.conn.execute(
            "SELECT id, username, auth_token FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        rows = self.conn.execute("SELECT id, username, auth_token FROM users ORDER BY username").fetchall()
        return [self._row_to_user(row) for row in rows]

    def add_debt(
        self,
        borrower_id: int,
        lender_id: int,
        amount: float,
        description: str,
        status: str = "pending",
    ) -> int:
        if borrower_id == lender_id:
            raise ValueError("Borrower and lender must be different users.")
        if amount <= 0:
            raise ValueError("Debt amount must be positive.")

        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO debts (borrower_id, lender_id, amount, description, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (borrower_id, lender_id, float(amount), description.strip(), status),
            )
        return int(cur.lastrowid)

    def list_pending_debts_for_borrower(self, borrower_id: int) -> list[DebtRecord]:
        rows = self.conn.execute(
            """
            SELECT d.*, b.username AS borrower_username, l.username AS lender_username
            FROM debts d
            JOIN users b ON b.id = d.borrower_id
            JOIN users l ON l.id = d.lender_id
            WHERE d.borrower_id = ? AND d.status = 'pending'
            ORDER BY d.created_at, d.id
            """,
            (borrower_id,),
        ).fetchall()
        return [self._row_to_debt(row) for row in rows]

    def get_pending_for_user(self, username: str) -> list[DebtRecord]:
        normalized = self._normalize_username(username)
        rows = self.conn.execute(
            """
            SELECT d.*, b.username AS borrower_username, l.username AS lender_username
            FROM debts d
            JOIN users b ON b.id = d.borrower_id
            JOIN users l ON l.id = d.lender_id
            WHERE b.username = ? AND d.status = 'pending'
            ORDER BY d.created_at, d.id
            """,
            (normalized,),
        ).fetchall()
        return [self._row_to_debt(row) for row in rows]

    def list_debts(self, status: str | None = None) -> list[DebtRecord]:
        sql = """
            SELECT d.*, b.username AS borrower_username, l.username AS lender_username
            FROM debts d
            JOIN users b ON b.id = d.borrower_id
            JOIN users l ON l.id = d.lender_id
        """
        params: tuple[str, ...] = ()
        if status is not None:
            sql += " WHERE d.status = ?"
            params = (status,)
        sql += " ORDER BY d.created_at DESC, d.id DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_debt(row) for row in rows]

    def list_approved_debts_for_engine(self) -> list[DebtRecord]:
        return self.list_approved()

    def list_approved(self) -> list[DebtRecord]:
        rows = self.conn.execute(
            """
            SELECT d.*, b.username AS borrower_username, l.username AS lender_username
            FROM debts d
            JOIN users b ON b.id = d.borrower_id
            JOIN users l ON l.id = d.lender_id
            WHERE d.status = 'approved'
            ORDER BY d.id
            """
        ).fetchall()
        return [self._row_to_debt(row) for row in rows]

    def update_debt_status(self, debt_id: int, borrower_id: int, status: str) -> bool:
        if status not in {"approved", "rejected"}:
            raise ValueError("Debt status must be approved or rejected.")

        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE debts
                SET status = ?
                WHERE id = ? AND borrower_id = ? AND status = 'pending'
                """,
                (status, debt_id, borrower_id),
            )
        return cur.rowcount == 1

    def update_status(self, debt_id: int, new_status: str) -> bool:
        if new_status not in {"approved", "rejected"}:
            raise ValueError("Debt status must be approved or rejected.")

        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE debts
                SET status = ?
                WHERE id = ? AND status = 'pending'
                """,
                (new_status, debt_id),
            )
        return cur.rowcount == 1

    def add_laundry_job(self, user_id: int, vruntime: float = 0.0, weight: float = 1.0, status: str = "waiting") -> int:
        if weight <= 0:
            raise ValueError("Laundry weight must be positive.")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO laundry_queue (user_id, vruntime, weight, status) VALUES (?, ?, ?, ?)",
                (user_id, float(vruntime), float(weight), status),
            )
        return int(cur.lastrowid)

    def list_waiting_laundry_jobs(self) -> list[LaundryRecord]:
        rows = self.conn.execute(
            """
            SELECT q.*, u.username
            FROM laundry_queue q
            JOIN users u ON u.id = q.user_id
            WHERE q.status = 'waiting'
            ORDER BY q.id
            """
        ).fetchall()
        return [self._row_to_laundry(row) for row in rows]

    def complete_laundry_job(self, job_id: int, projected_vruntime: float) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE laundry_queue SET vruntime = ?, status = 'completed' WHERE id = ?",
                (float(projected_vruntime), job_id),
            )

    def add_barter_node(self, user_id: int, has_skill_id: int, wants_skill_id: int) -> int:
        if has_skill_id == wants_skill_id:
            raise ValueError("A barter offer must trade different skills.")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO barter_nodes (user_id, has_skill_id, wants_skill_id) VALUES (?, ?, ?)",
                (user_id, has_skill_id, wants_skill_id),
            )
        return int(cur.lastrowid)

    def list_barter_nodes(self) -> list[BarterRecord]:
        rows = self.conn.execute(
            """
            SELECT n.*, u.username
            FROM barter_nodes n
            JOIN users u ON u.id = n.user_id
            ORDER BY n.id
            """
        ).fetchall()
        return [self._row_to_barter(row) for row in rows]

    def create_trip_pool(self, trip_name: str, total_budget: float, status: str = "planned") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO trip_pools (trip_name, total_budget, status) VALUES (?, ?, ?)",
                (trip_name.strip(), float(total_budget), status),
            )
        return int(cur.lastrowid)

    @staticmethod
    def _normalize_username(username: str) -> str:
        normalized = username.strip().lower()
        if not normalized:
            raise ValueError("Username cannot be empty.")
        return normalized

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(id=int(row["id"]), username=str(row["username"]), auth_token=str(row["auth_token"]))

    @staticmethod
    def _row_to_debt(row: sqlite3.Row) -> DebtRecord:
        return DebtRecord(
            id=int(row["id"]),
            borrower_id=int(row["borrower_id"]),
            lender_id=int(row["lender_id"]),
            amount=float(row["amount"]),
            description=str(row["description"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            borrower_username=row["borrower_username"] if "borrower_username" in row.keys() else None,
            lender_username=row["lender_username"] if "lender_username" in row.keys() else None,
        )

    @staticmethod
    def _row_to_laundry(row: sqlite3.Row) -> LaundryRecord:
        return LaundryRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            vruntime=float(row["vruntime"]),
            weight=float(row["weight"]),
            status=str(row["status"]),
            username=row["username"] if "username" in row.keys() else None,
        )

    @staticmethod
    def _row_to_barter(row: sqlite3.Row) -> BarterRecord:
        return BarterRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            has_skill_id=int(row["has_skill_id"]),
            wants_skill_id=int(row["wants_skill_id"]),
            username=row["username"] if "username" in row.keys() else None,
        )


def ensure_users(repo: DormiXRepository, usernames: Iterable[str]) -> dict[str, User]:
    users: dict[str, User] = {}
    for username in usernames:
        normalized = DormiXRepository._normalize_username(username)
        user = repo.get_user_by_username(normalized)
        if user is None:
            user = repo.create_user(normalized, f"token-{normalized}")
        users[normalized] = user
    return users


DebtRepository = DormiXRepository
BarterRepository = DormiXRepository
