import os
import subprocess

JUDGES_DIR = os.path.dirname(os.path.abspath(__file__))

# logical binary name -> source file. jsoncpp is pulled in via the amalgamated
# jsoncpp/json.h, so each judge compiles from a single .cpp.
JUDGE_SOURCES = {
    'snake_judge': 'snake_judge.cpp',
    'msnake_judge': 'snakem_judge.cpp',
    'tank2_judge': 'tank2_judge.cpp',
}


def _binary_name(name):
    return name + ('.exe' if os.name == 'nt' else '')


def judge_binary_path(name):
    """Absolute path to a judge binary for the current platform."""
    if name not in JUDGE_SOURCES:
        raise KeyError(f"unknown judge: {name}")
    return os.path.join(JUDGES_DIR, _binary_name(name))


def _needs_build(binary, src_path):
    if not os.path.exists(binary):
        return True
    return os.path.getmtime(binary) < os.path.getmtime(src_path)


def ensure_judges_built(force=False):
    """Compile any judge binary that is missing or older than its source.

    Best-effort: a compiler failure for one judge is logged, not raised, so the
    rest of the app (and Python-only games) still start. Snake/Tank will surface
    a clear 'judge not found' error at match time if their binary never built.
    """
    for name, src in JUDGE_SOURCES.items():
        binary = judge_binary_path(name)
        src_path = os.path.join(JUDGES_DIR, src)
        if not force and not _needs_build(binary, src_path):
            continue
        args = ['g++', '-std=c++17', '-O2', src_path, '-o', binary]
        try:
            result = subprocess.run(args, capture_output=True)
        except FileNotFoundError:
            print(f"[judges] g++ not found; cannot build '{name}'. Install a C++ compiler.")
            continue
        if result.returncode != 0:
            print(f"[judges] failed to build '{name}':\n{result.stderr.decode('utf-8', 'replace')}")
            continue
        try:
            os.chmod(binary, 0o755)
        except OSError:
            pass
        print(f"[judges] built {os.path.basename(binary)}")
