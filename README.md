
# Turbo C Upgrade (MVP)

A Python desktop wrapper for Turbo C running in DOSBox.

## MVP Features
- One-click DOSBox + Turbo C launch
- Compile and run triggers
- Friendly diagnostics panel (best-effort parser)

## Prerequisites
- Windows 11
- Python 3.11+
- DOSBox installed (or DOSBox Staging)
- Local legal Turbo C files

## Quick Start
1. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
2. Run the app:
   ```powershell
   python -m src.app.main
   ```
3. On first launch, open Settings in the UI and set:
   - DOSBox executable path
   - Turbo C root directory
   - Working project directory

## Path Mapping (for TURBOC3 layout)
Use the following mapping based on your directory tree:

- DOSBox executable:
   - `<TURBOC3>\\Turbo C++\\DOSBox-0.74\\DOSBox.exe`
- Turbo C root:
   - `<TURBOC3>`
- Project root:
   - `<TURBOC3>\\Projects` (or `<TURBOC3>\\NATHAN` if that is your active source folder)

Then in the UI:
- Source file: enter path relative to project root, e.g. `HELLO.C` or `Intro\\EXPT1.C`
- Executable: enter output name in project root, e.g. `HELLO.EXE`

## Notes
- Graphics output from Turbo C programs appears in the DOSBox window.
- Build logs and diagnostics appear in this app.
