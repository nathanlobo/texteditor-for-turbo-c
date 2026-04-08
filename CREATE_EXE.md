# Creating a .exe

The quickest and most reliable way to package this app as a Windows executable is to use PyInstaller in `onedir` mode.

## Steps

1. Install PyInstaller:

```powershell
python -m pip install pyinstaller
```

2. Build the app:

```powershell
python -m PyInstaller --noconfirm --clean --onedir --windowed --name "Turbo C Editor" --icon src/app/assets/dos-codinx.ico --add-data "src/app/assets;src/app/assets" src/app/main.py
```

## Output

The executable will be created at:

```text
dist/Turbo C Editor/Turbo C Editor.exe
```

## Notes

- `onedir` is usually the best choice for PySide6 apps because it is more reliable than `onefile`.
- This packages the Python app only.
- DOSBox and Turbo C still need to be present separately unless you bundle them into your app distribution as well.
- The build uses `src/app/assets/dos-codinx.ico` for the Windows app/taskbar icon. The in-app logo still comes from `src/app/assets/icon.png`.
- Windows will still append `.exe` because that is the file extension, but the spaced `--name` keeps the displayed app name cleaner.
