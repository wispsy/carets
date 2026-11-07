"""Qualify wheel/source installation and synthetic application contracts."""

from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = Path(sys.argv[1]).resolve()
    artifacts = sorted([*directory.glob("*.whl"), *directory.glob("*.tar.gz")])
    assert len(artifacts) == 2
    for artifact in artifacts:
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary)
            environment = outside / "env"
            subprocess.run(["uv", "venv", str(environment), "--python", sys.executable], check=True)
            python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            subprocess.run(["uv", "pip", "install", "--python", str(python), str(artifact)], check=True, cwd=outside)
            subprocess.run([str(python), "-I", "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"], check=True, cwd=outside)
            subprocess.run(["uv", "pip", "check", "--python", str(python)], check=True, cwd=outside)


if __name__ == "__main__":
    main()
