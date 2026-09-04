"""Build and acceptance-test a Vaelor portable package in an isolated directory."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILES = {
    "config/api_access.json",
    "config/network.json",
    "config/setup_complete.json",
}
FORBIDDEN_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "dist"}
REQUIRED_FILES = {
    "INSTALL.bat",
    "ALPHA_README.txt",
    "requirements.txt",
    "api/server.py",
    "core/runtime.py",
    "web/index.html",
    "installer/Install-Vaelor-Alpha.ps1",
    "installer/init_local_config.py",
}


def _powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        raise RuntimeError("PowerShell 5.1+ is required to build the Windows package")
    return executable


def _archive_root(names: list[str]) -> str:
    roots = {name.split("/", 1)[0] for name in names if name and not name.startswith("/")}
    if len(roots) != 1:
        raise RuntimeError(f"archive must contain exactly one root folder, found {sorted(roots)}")
    return roots.pop()


def inspect_archive(zip_path: Path, source_root: Path) -> dict[str, object]:
    expected_hash = (zip_path.with_suffix(zip_path.suffix + ".sha256")).read_text(
        encoding="ascii"
    ).strip().lower()
    actual_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError("package SHA256 does not match its checksum file")

    with zipfile.ZipFile(zip_path) as archive:
        names = [info.filename.replace("\\", "/").rstrip("/") for info in archive.infolist()]
        root_name = _archive_root(names)
        relative = {
            name[len(root_name) + 1:]
            for name in names
            if name.startswith(root_name + "/") and len(name) > len(root_name) + 1
        }
        missing = sorted(REQUIRED_FILES - relative)
        if missing:
            raise RuntimeError(f"package is missing required files: {missing}")
        forbidden = sorted(
            name for name in relative
            if name in FORBIDDEN_FILES or any(part in FORBIDDEN_PARTS for part in Path(name).parts)
        )
        if forbidden:
            raise RuntimeError(f"package contains private/build state: {forbidden[:10]}")

        legacy_server = b"S:\\" + b"VeilorServer"
        personal_patterns = [
            re.compile(re.escape(str(Path.home())).encode("utf-8"), re.IGNORECASE),
            re.compile(re.escape(str(source_root)).encode("utf-8"), re.IGNORECASE),
            re.compile(re.escape(legacy_server), re.IGNORECASE),
        ]
        leaks: list[str] = []
        for info in archive.infolist():
            if info.is_dir() or info.file_size > 2_000_000:
                continue
            payload = archive.read(info)
            if any(pattern.search(payload) for pattern in personal_patterns):
                leaks.append(info.filename)
        if leaks:
            raise RuntimeError(f"package contains builder-specific paths: {leaks[:10]}")

    return {"sha256": actual_hash, "root": root_name, "files": len(relative)}


def smoke_test_extracted(package_root: Path) -> None:
    subprocess.run(
        [sys.executable, str(package_root / "installer" / "init_local_config.py"),
         str(package_root), "--force"],
        cwd=package_root, check=True, capture_output=True, text=True,
    )
    if (package_root / "config" / "api_access.json").exists():
        raise RuntimeError("fresh initialization unexpectedly created remote API credentials")
    network = json.loads((package_root / "config" / "network.json").read_text(encoding="utf-8-sig"))
    if network.get("host") not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("fresh package did not default to loopback networking")

    smoke = """
from pathlib import Path
from fastapi.testclient import TestClient
import api.server as server
root = Path.cwd().resolve()
assert root in Path(server.__file__).resolve().parents
client = TestClient(server.app)
health = client.get('/health')
assert health.status_code == 200 and health.json().get('version')
assert client.get('/auth/status').json() == {
    'authentication_required': False, 'authenticated': True
}
page = client.get('/')
assert page.status_code == 200 and 'Vaelor' in page.text
"""
    environment = dict(__import__("os").environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, "-c", smoke], cwd=package_root, env=environment,
        check=True, capture_output=True, text=True,
    )


def verify(source_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    with tempfile.TemporaryDirectory(prefix="vaelor-package-acceptance-") as temp:
        work = Path(temp)
        subprocess.run(
            [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(source_root / "installer" / "Build-AlphaPackage.ps1"),
             "-SourceDir", str(source_root), "-OutDir", str(work)],
            cwd=source_root, check=True,
        )
        archives = list(work.glob("Vaelor-Alpha-*.zip"))
        if len(archives) != 1:
            raise RuntimeError(f"expected one package archive, found {len(archives)}")
        details = inspect_archive(archives[0], source_root)
        extract_dir = work / "extracted"
        with zipfile.ZipFile(archives[0]) as archive:
            archive.extractall(extract_dir)
        package_root = extract_dir / str(details["root"])
        smoke_test_extracted(package_root)
        details["runtime_smoke"] = "passed"
        return details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = verify(args.source)
    except (OSError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"CLEAN PACKAGE ACCEPTANCE FAILED: {exc}", file=sys.stderr)
        return 1
    print("CLEAN PACKAGE ACCEPTANCE PASSED")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
