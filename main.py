from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
import tempfile
import smtplib
import random
from email.message import EmailMessage
from pathlib import Path
from typing import Sequence

from database import BarterRepository, DebtRecord, DebtRepository, DormiXRepository, LaundryRecord, User

BASE_DIR = Path(__file__).resolve().parent
ENGINE_DIR = BASE_DIR / "c_engines"
FALLBACK_BUILD_DIR = Path(tempfile.gettempdir()) / "dormix_engines"
CURRENT_USER: str | None = None
ENGINEERING_SKILLS = {
    "1": "Low-Level Systems (C/C++)",
    "2": "Database Architecture & SQLite",
    "3": "Data Analysis (Python/Pandas)",
    "4": "OS Concepts & Memory Management",
    "5": "Frontend UI",
    "6": "Mathematics & Graph Algorithms",
}

# --- C STRUCTS ---
class CDebt(ctypes.Structure):
    _fields_ = [("from_id", ctypes.c_int), ("to_id", ctypes.c_int), ("amount", ctypes.c_double)]

class CTransaction(ctypes.Structure):
    _fields_ = [("from_id", ctypes.c_int), ("to_id", ctypes.c_int), ("amount", ctypes.c_double)]

class CSettlementResult(ctypes.Structure):
    _fields_ = [("count", ctypes.c_int), ("transactions", ctypes.POINTER(CTransaction))]

class CLaundryJob(ctypes.Structure):
    _fields_ = [("user_id", ctypes.c_int), ("vruntime", ctypes.c_double), ("weight", ctypes.c_double)]

class CLaundryResult(ctypes.Structure):
    _fields_ = [("winning_index", ctypes.c_int), ("user_id", ctypes.c_int), ("score", ctypes.c_double), ("projected_vruntime", ctypes.c_double)]

class CBarterNode(ctypes.Structure):
    _fields_ = [("user_id", ctypes.c_int), ("has_skill", ctypes.c_int), ("wants_skill", ctypes.c_int)]

class CTradeLoop(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int), ("users", ctypes.c_int * 4), ("has_skills", ctypes.c_int * 4), ("wants_skills", ctypes.c_int * 4)]

class CBarterResult(ctypes.Structure):
    _fields_ = [("count", ctypes.c_int), ("loops", ctypes.POINTER(CTradeLoop))]


class EngineLoader:
    def __init__(self) -> None:
        self.suffix = ".dll" if platform.system() == "Windows" else ".so"

    def load_debt(self) -> ctypes.CDLL:
        lib = self._load("debt_solver")
        lib.settle_debts.argtypes = [ctypes.POINTER(CDebt), ctypes.c_int]
        lib.settle_debts.restype = ctypes.POINTER(CSettlementResult)
        lib.free_results.argtypes = [ctypes.POINTER(CSettlementResult)]
        lib.free_results.restype = None
        return lib

    def load_laundry(self) -> ctypes.CDLL:
        lib = self._load("cfs_laundry")
        lib.schedule_laundry.argtypes = [ctypes.POINTER(CLaundryJob), ctypes.c_int, ctypes.c_double]
        lib.schedule_laundry.restype = ctypes.POINTER(CLaundryResult)
        lib.free_results.argtypes = [ctypes.POINTER(CLaundryResult)]
        lib.free_results.restype = None
        return lib

    def load_barter(self) -> ctypes.CDLL:
        lib = self._load("barter_graph")
        lib.find_trade_loops.argtypes = [ctypes.POINTER(CBarterNode), ctypes.c_int]
        lib.find_trade_loops.restype = ctypes.POINTER(CBarterResult)
        lib.free_results.argtypes = [ctypes.POINTER(CBarterResult)]
        lib.free_results.restype = None
        return lib

    def _load(self, name: str) -> ctypes.CDLL:
        candidates = [ENGINE_DIR / f"{name}{self.suffix}", FALLBACK_BUILD_DIR / f"{name}{self.suffix}"]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            build_dir = compile_engines()
            path = build_dir / f"{name}{self.suffix}"
        if not path.exists():
            raise FileNotFoundError(f"Missing compiled engine {name}")
        return ctypes.CDLL(str(path))


def compile_engines() -> Path:
    compiler = os.environ.get("CC", "gcc")
    suffix = ".dll" if platform.system() == "Windows" else ".so"
    output_dir = choose_build_dir()
    output = lambda name: f"{name}{suffix}" if output_dir == ENGINE_DIR else str(output_dir / f"{name}{suffix}")
    commands = [
        [compiler, "-O2", "-shared", "-o", output("debt_solver"), "debt_solver.c"],
        [compiler, "-O2", "-shared", "-o", output("cfs_laundry"), "cfs_laundry.c"],
        [compiler, "-O2", "-shared", "-o", output("barter_graph"), "barter_graph.c"],
    ]
    if platform.system() != "Windows":
        for command in commands:
            command.insert(2, "-fPIC")

    for command in commands:
        subprocess.run(command, check=True, cwd=ENGINE_DIR)
    return output_dir

def choose_build_dir() -> Path:
    if can_write_to(ENGINE_DIR): return ENGINE_DIR
    FALLBACK_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    return FALLBACK_BUILD_DIR

def can_write_to(path: Path) -> bool:
    probe = path / ".dormix_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError: return False

def settle_debts(repo: DebtRepository) -> list[tuple[int, int, float]]:
    approved_debts = repo.list_approved()
    if not approved_debts: return []

    debt_array_type = CDebt * len(approved_debts)
    c_debts = debt_array_type(*[CDebt(from_id=debt.borrower_id, to_id=debt.lender_id, amount=debt.amount) for debt in approved_debts])

    lib = EngineLoader().load_debt()
    result_ptr = lib.settle_debts(c_debts, len(c_debts))
    try:
        if not result_ptr: raise RuntimeError("Debt engine returned a null result pointer.")
        result = result_ptr.contents
        return [(int(result.transactions[i].from_id), int(result.transactions[i].to_id), round(float(result.transactions[i].amount), 2)) for i in range(result.count)]
    finally:
        if result_ptr: lib.free_results(result_ptr)

def choose_laundry_winner(repo: DormiXRepository, runtime_increment: float) -> tuple[LaundryRecord, float, float] | None:
    jobs = repo.list_waiting_laundry_jobs()
    if not jobs: return None
    job_array_type = CLaundryJob * len(jobs)
    c_jobs = job_array_type(*[CLaundryJob(user_id=job.user_id, vruntime=job.vruntime, weight=job.weight) for job in jobs])
    lib = EngineLoader().load_laundry()
    result_ptr = lib.schedule_laundry(c_jobs, len(c_jobs), float(runtime_increment))
    try:
        if not result_ptr: raise RuntimeError("Laundry engine returned a null result pointer.")
        result = result_ptr.contents
        if result.winning_index < 0: return None
        return jobs[result.winning_index], float(result.score), float(result.projected_vruntime)
    finally:
        if result_ptr: lib.free_results(result_ptr)

def find_barter_loops(repo: DormiXRepository) -> list[list[tuple[int, int, int]]]:
    nodes = repo.list_barter_nodes()
    if not nodes: return []
    node_array_type = CBarterNode * len(nodes)
    c_nodes = node_array_type(*[CBarterNode(user_id=node.user_id, has_skill=node.has_skill_id, wants_skill=node.wants_skill_id) for node in nodes])
    lib = EngineLoader().load_barter()
    result_ptr = lib.find_trade_loops(c_nodes, len(c_nodes))
    try:
        if not result_ptr: raise RuntimeError("Barter engine returned a null result pointer.")
        result = result_ptr.contents
        loops = []
        for i in range(result.count):
            loop = result.loops[i]
            loops.append([(int(loop.users[j]), int(loop.has_skills[j]), int(loop.wants_skills[j])) for j in range(loop.length)])
        return loops
    finally:
        if result_ptr: lib.free_results(result_ptr)


def send_otp_email(target_email: str, otp_code: str) -> None:
    """Mock dispatcher for local testing"""
    print("\n" + "="*50)
    print(f"🔒 MOCK EMAIL DISPATCHER")
    print(f"To: {target_email}")
    print(f"Subject: Your DormiX Login Code")
    print(f"Body: Your 6-digit OTP is {otp_code}. It expires in 5 minutes.")
    print("="*50 + "\n")


class DormiXCLI:
    def __init__(self, repo: DormiXRepository) -> None:
        self.repo = repo
        self.current_user: User | None = None

    def run(self) -> None:
        global CURRENT_USER
        print("DormiX: Polyglot Resource & Debt Scheduler")
        current_email = input("Login as (enter your student email): ").strip().lower()
        self.current_user = self.prompt_or_create_user(current_email)
        CURRENT_USER = self.current_user.email
        print(f"\nLogged in as {self.current_user.username} ({CURRENT_USER})")

        while True:
            print("\n1. Create user\n2. Switch user\n3. Log debt\n4. Check Inbox (Pending Approvals)\n5. Split bill N ways\n6. Settle approved debts\n7. Add laundry job\n8. Schedule laundry\n9. Add barter offer\n10. Find barter loops\n11. List debts\n0. Exit")
            choice = input("> ").strip()
            try:
                if choice == "1": self.create_user()
                elif choice == "2": self.login()
                elif choice == "3": self.log_debt()
                elif choice == "4": self.approvals()
                elif choice == "5": self.split_bill()
                elif choice == "6": self.display_settlements()
                elif choice == "7": self.add_laundry_job()
                elif choice == "8": self.schedule_laundry()
                elif choice == "9": self.add_barter_offer()
                elif choice == "10": self.display_barter_loops()
                elif choice == "11": self.list_debts()
                elif choice == "0": break
                else: print("Unknown option.")
            except (ValueError, FileNotFoundError, subprocess.CalledProcessError, RuntimeError) as exc:
                print(f"Error: {exc}")

    def create_user(self) -> None:
        email = input("Student Email: ").strip().lower()
        if self.repo.get_user_by_email(email):
            print(f"Error: Account for '{email}' already exists!")
            return
        username = input("Display Name: ")
        user = self.repo.create_user(email, username)
        print(f"Created user #{user.id}: {user.username} ({user.email})")

    def login(self) -> None:
        global CURRENT_USER
        email = input("Student Email: ").strip().lower()
        user = self.repo.get_user_by_email(email)
        
        if user is None:
            print("No such user found. Please create an account first.")
            return
            
        otp_code = str(random.randint(100000, 999999))
        self.repo.set_otp(email, otp_code)
        send_otp_email(email, otp_code)
        
        attempts = 3
        while attempts > 0:
            entered_code = input(f"Enter the 6-digit code sent to {email}: ").strip()
            if self.repo.verify_otp(email, entered_code):
                self.current_user = user
                CURRENT_USER = user.email
                print(f"\n✅ Authentication successful. Welcome back, {user.username}!")
                return
            else:
                attempts -= 1
                print(f"❌ Invalid or expired code. {attempts} attempts remaining.")
                
        print("Authentication failed.")

    def log_debt(self) -> None:
        lender = self.require_user()
        borrower = self.prompt_user("Who owes you? (Email): ")
        amount = read_float("Amount: ")
        description = input("Description: ").strip() or "Dorm debt"
        debt_id = self.repo.add_debt(borrower_id=borrower.id, lender_id=lender.id, amount=amount, description=description, status="pending")
        print(f"Debt #{debt_id} is pending approval from {borrower.username}.")

    def approvals(self) -> None:
        user = self.require_user()
        check_inbox(self.repo, user.email)

    def split_bill(self) -> None:
        payer = self.prompt_user("Who paid? (Email): ")
        total = read_float("Total amount: ")
        participant_emails = parse_emails(input("Participants' emails, comma-separated: "))
        participants = [self.prompt_or_create_user(email) for email in participant_emails]
        if payer.id not in {user.id for user in participants}: participants.append(payer)
        if len(participants) < 2: raise ValueError("A split needs at least two participants.")
        share = round(total / len(participants), 2)
        description = input("Bill description: ").strip() or f"{len(participants)}-way split"
        created = 0
        for participant in participants:
            if participant.id == payer.id: continue
            self.repo.add_debt(borrower_id=participant.id, lender_id=payer.id, amount=share, description=description, status="pending")
            created += 1
        print(f"Created {created} pending debt edges at {money(share)} each.")

    def display_settlements(self) -> None:
        users_by_id = {user.id: user.username for user in self.repo.list_users()}
        transactions = settle_debts(self.repo)
        if not transactions:
            print("No approved debt to settle.")
            return
        print("Optimal settlement plan from approved debts only:")
        for from_id, to_id, amount in transactions:
            print(f"- {users_by_id.get(from_id, from_id)} pays {users_by_id.get(to_id, to_id)} {money(amount)}")

    def add_laundry_job(self) -> None:
        user = self.prompt_user("Laundry user email: ")
        vruntime = read_float("Current vruntime [0]: ", default=0.0)
        weight = read_float("Weight [1]: ", default=1.0)
        job_id = self.repo.add_laundry_job(user.id, vruntime, weight)
        print(f"Added laundry job #{job_id}.")

    def schedule_laundry(self) -> None:
        runtime_increment = read_float("Runtime increment [1]: ", default=1.0)
        winner = choose_laundry_winner(self.repo, runtime_increment)
        if winner is None:
            print("No waiting laundry jobs.")
            return
        job, score, projected_vruntime = winner
        print(f"Winner: {job.username} (job #{job.id}), score={score:.4f}, projected vruntime={projected_vruntime:.4f}")
        if input("Mark this job completed? [y/N] ").strip().lower() == "y":
            self.repo.complete_laundry_job(job.id, projected_vruntime)
            print("Laundry job completed.")

    def add_barter_offer(self) -> None:
        add_barter(self.repo)

    def display_barter_loops(self) -> None:
        users_by_id = {user.id: user.username for user in self.repo.list_users()}
        loops = find_barter_loops(self.repo)
        if not loops:
            print("No barter loops of depth <= 4 found.")
            return
        for idx, loop in enumerate(loops, start=1):
            print(f"Loop #{idx}:")
            for user_id, has_skill, wants_skill in loop:
                print(f"- {users_by_id.get(user_id, user_id)} offers {skill_name(has_skill)} and wants {skill_name(wants_skill)}")

    def list_debts(self) -> None:
        status = input("Filter status [all/pending/approved/rejected]: ").strip().lower()
        debts = self.repo.list_debts(None if status in {"", "all"} else status)
        if not debts: print("No debts found.")
        for debt in debts: print(format_debt(debt))

    def prompt_user(self, prompt: str) -> User:
        email = input(prompt).strip().lower()
        user = self.repo.get_user_by_email(email)
        if user is None: raise ValueError(f"No account found for email: {email}")
        return user

    def prompt_or_create_user(self, email: str) -> User:
        user = self.repo.get_user_by_email(email)
        if user is not None: return user
        print(f"No account found for {email}. Let's create one.")
        username = input("Enter Display Name: ")
        return self.repo.create_user(email, username)

    def require_user(self) -> User:
        if self.current_user is None: raise ValueError("Please login first.")
        return self.current_user


def choose_skill(label: str) -> int:
    print(label + ":")
    for skill_id, name in ENGINEERING_SKILLS.items(): print(f"{skill_id}. {name}")
    selected = input("> ").strip()
    if selected not in ENGINEERING_SKILLS: raise ValueError("Skill must be selected from the strict taxonomy.")
    return skill_id_from_name(ENGINEERING_SKILLS[selected])

def skill_id_from_name(skill: str) -> int:
    for skill_id, name in ENGINEERING_SKILLS.items():
        if name == skill: return int(skill_id)
    raise ValueError("Skill must come from the strict taxonomy.")

def skill_name(skill_id: int) -> str:
    return ENGINEERING_SKILLS[str(skill_id)]

def check_inbox(repo: DebtRepository, current_email: str) -> None:
    pending = repo.get_pending_for_user(current_email)
    if not pending:
        print("No pending approvals.")
        return
    for debt in pending:
        print(f"#{debt.id}: {debt.lender_username} says you owe them {money(debt.amount)} for {debt.description} ({debt.created_at})")
        decision = input("Type A to approve, R to reject, or Enter to skip: ").strip().upper()
        if decision == "A":
            repo.update_status(debt.id, "approved")
            print("Approved. The Hisaab Engine will now calculate this.")
        elif decision == "R":
            repo.update_status(debt.id, "rejected")
            print("Rejected.")

def add_barter(repo: BarterRepository) -> None:
    email = CURRENT_USER or input("Barter user email: ").strip().lower()
    user = repo.get_user_by_email(email)
    if user is None:
        username = input("Enter Display Name for new account: ")
        user = repo.create_user(email, username)

    has_skill = choose_skill("Skill you have")
    wants_skill = choose_skill("Skill you want")
    node_id = repo.add_barter_node(user.id, has_skill, wants_skill)
    print(f"Added barter node #{node_id}: {user.username} offers {skill_name(has_skill)} and wants {skill_name(wants_skill)}.")

def read_float(prompt: str, default: float | None = None) -> float:
    raw = input(prompt).strip()
    if raw == "" and default is not None: return default
    return float(raw)

def parse_emails(raw: str) -> list[str]:
    emails = [e.strip().lower() for e in raw.split(",") if e.strip()]
    if not emails: raise ValueError("At least one participant is required.")
    return emails

def money(amount: float) -> str: return f"INR {amount:.2f}"

def format_debt(debt: DebtRecord) -> str:
    return f"#{debt.id} [{debt.status}] {debt.borrower_username} owes {debt.lender_username} {money(debt.amount)} - {debt.description}"

def run_smoke_demo() -> None:
    repo = DormiXRepository(":memory:")
    try:
        alice = repo.create_user("alice@vitstudent.ac.in", "Alice")
        bob = repo.create_user("bob@vitstudent.ac.in", "Bob")
        charlie = repo.create_user("charlie@vitstudent.ac.in", "Charlie")
        repo.add_debt(bob.id, alice.id, 50.0, "chai", "approved")
        repo.add_debt(alice.id, charlie.id, 20.0, "snacks", "approved")
        assert settle_debts(repo), "expected at least one settlement"
        print("Smoke demo passed.")
    finally:
        repo.close()

def dashboard(repo: DebtRepository) -> None:
    DormiXCLI(repo).run()

def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--build-engines"]:
        build_dir = compile_engines()
        print(f"Compiled C engines to {build_dir}.")
        return 0
    if args == ["--smoke-demo"]:
        run_smoke_demo()
        return 0

    repo = DormiXRepository(BASE_DIR / "dormix.db")
    try:
        dashboard(repo)
    finally:
        repo.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())