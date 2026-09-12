"""Build a relocatable desktop runtime from the privacy-checked source package."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.verify_clean_package import inspect_archive, _powershell


def build(source, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for location in (output, Path(tempfile.gettempdir())):
        if shutil.disk_usage(location).free < 512 * 1024 * 1024:
            raise ValueError(f"At least 512 MiB free is required at {location}; choose another output or TEMP directory.")
    if (output / "Vaelor").exists():
        raise ValueError("Output already contains Vaelor; choose an empty output directory.")
    with tempfile.TemporaryDirectory(prefix="vaelor-desktop-build-") as temp:
        work = Path(temp)
        subprocess.run([_powershell(), "-NoProfile", "-File", str(source / "installer/Build-AlphaPackage.ps1"),
                        "-SourceDir", str(source), "-OutDir", str(work)], check=True)
        archive = next(work.glob("Vaelor-Alpha-*.zip"))
        metadata = inspect_archive(archive, source)
        with zipfile.ZipFile(archive) as package:
            package.extractall(work / "source")
        stage = work / "source" / metadata["root"]
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
                   "--name", "Vaelor", "--distpath", str(output), "--workpath", str(work / "build"),
                   "--specpath", str(work), "--paths", str(stage), "--add-data", f"{stage}{os.pathsep}.",
                   "--collect-submodules", "core", "--collect-submodules", "spellbook",
                   "--collect-submodules", "uvicorn", "--collect-all", "webview",
                   "--hidden-import", "api.server", "--hidden-import", "installer.init_local_config",
                   str(stage / "desktop/vaelor_app.py")]
        log_path = output / "build.log"
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=stage, stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode:
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-35:])
            raise RuntimeError(f"Desktop build failed; see {log_path}\n{tail}")
    destination = output / "Vaelor"
    if not (destination / "Vaelor.exe").is_file() or (destination / ".venv").exists():
        raise RuntimeError("Frozen runtime was not built correctly.")
    (destination / "HOW-TO-USE.txt").write_text(
        "Extract the complete folder to a writable location and run Vaelor.exe.\n"
        "Python is bundled. Windows WebView2 and a configured model backend are still required.\n"
        "Optional: run Install-Desktop.ps1 for a per-user installation and shortcut.\n"
        "Keep the _internal folder beside the executable.\n", encoding="utf-8")
    shutil.copy2(source / "installer/Install-Desktop.ps1", destination / "Install-Desktop.ps1")
    archive = Path(shutil.make_archive(str(output / "Vaelor-Desktop"), "zip", output, "Vaelor"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "\n", encoding="ascii")
    return {"exe": str(destination / "Vaelor.exe"), "archive": str(archive), "sha256": digest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source.resolve(), args.output), indent=2))
