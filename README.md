# DormiX

DormiX is a polyglot dorm resource and debt scheduler:

- Python 3.13 handles the CLI, authentication simulation, approvals, SQLite, and normalization.
- C shared libraries handle only numeric algorithms and graph traversal.
- Python uses `ctypes` with explicit `argtypes` / `restype` declarations.
- Every C result pointer is released through the matching `free_results` function in a `try...finally` block.

## Files

- `database.py` - SQLite repository layer with WAL mode and normalized tables.
- `main.py` - CLI, ctypes FFI bridge, business logic, and engine build helper.
- `c_engines/debt_solver.c` - greedy max/min heap settlement engine.
- `c_engines/cfs_laundry.c` - CFS-style laundry scheduler.
- `c_engines/barter_graph.c` - DFS barter loop matcher with max depth 4.

## Build

Install a C compiler such as GCC/MinGW on Windows, then run:

```powershell
python main.py --build-engines
```

The command emits `.dll` files on Windows and `.so` files on Linux/macOS.
If the project directory is not writable by subprocesses, DormiX automatically falls back to a temp build directory and loads the libraries from there.

## Smoke Test

```powershell
python main.py --smoke-demo
```

Or run the focused unit tests:

```powershell
python -B -m unittest discover -s tests
```

## Run

```powershell
python main.py
```

Approved debt filtering is enforced in Python before calling C:

```sql
SELECT ... FROM debts WHERE d.status = 'approved'
```

Pending and rejected debts never cross the FFI boundary.
