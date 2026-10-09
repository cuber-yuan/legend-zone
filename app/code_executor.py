import subprocess
import tempfile
import os
import sys
import shutil
from . import cpp_compiler


class CodeExecutor:
    """Runs one bot in a sandboxed subprocess.

    The bot lives as a directory (its "workdir") — for a single-file bot that
    directory just contains main.py / main.cpp; for zip-based bots it contains
    the extracted tree. Entry file is resolved by language at run time.
    """

    PYTHON_ENTRIES = ('__main__.py', 'main.py')
    CPP_ENTRIES = ('main.cpp', 'main.cc')

    def __init__(self, workdir: str, language: str = 'python3'):
        self.workdir = os.path.abspath(workdir) if workdir else workdir
        self.language = (language or 'python3').lower()

    def cleanup(self):
        pass

    def run(self, input_str: str) -> str:
        if self.language == 'python3':
            return self._run_python(input_str)
        if self.language == 'cpp':
            return self._run_cpp(input_str)
        raise ValueError(f"Unsupported language: {self.language}")

    def _resolve_entry(self, candidates):
        for name in candidates:
            path = os.path.join(self.workdir, name)
            if os.path.isfile(path):
                return path
        for fname in sorted(os.listdir(self.workdir)):
            if fname.endswith(candidates[-1][-3:]):
                return os.path.join(self.workdir, fname)
        raise RuntimeError(f"No entry file found under {self.workdir}")

    def _run_python(self, input_str: str) -> str:
        entry = self._resolve_entry(self.PYTHON_ENTRIES)
        try:
            env = self._get_sandbox_env()
            result = subprocess.run(
                [sys.executable, "-u", entry],
                input=input_str.encode('utf-8'),
                capture_output=True,
                timeout=10,
                check=True,
                cwd=self.workdir,
                env=env
            )
            return result.stdout.decode('utf-8')
        except subprocess.CalledProcessError as e:
            error_message = f"Bot code exited with error code {e.returncode}.\n" \
                            f"--- STDOUT ---\n{e.stdout.decode('utf-8')}\n" \
                            f"--- STDERR ---\n{e.stderr.decode('utf-8')}"
            print(error_message)
            raise RuntimeError("Bot execution failed. See server logs for details.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Python code execution timed out")

    def _run_cpp(self, input_str: str) -> str:
        entry = self._resolve_entry(self.CPP_ENTRIES)
        compiler = cpp_compiler.CppCompiler()
        exec_path = compiler.compile_file(entry)

        with tempfile.TemporaryDirectory() as sandbox_dir:
            temp_exec = os.path.join(sandbox_dir, os.path.basename(exec_path))
            shutil.copy2(exec_path, temp_exec)

            env = self._get_sandbox_env()
            try:
                result = subprocess.run(
                    [temp_exec],
                    input=input_str.encode('utf-8'),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    cwd=self.workdir,
                    env=env
                )
                if result.returncode != 0:
                    raise RuntimeError(f"C++ runtime error: {result.stderr.decode()}")
                return result.stdout.decode()
            except subprocess.TimeoutExpired:
                raise RuntimeError("C++ execution timed out")

    def _get_sandbox_env(self) -> dict:
        """Restricted env that still lets installed packages import.

        PYTHONIOENCODING is forced to utf-8 so Windows-side bots that print
        non-ASCII do not crash on the default cp936 codec.
        """
        env = dict(os.environ)
        env['PATH'] = os.environ.get('PATH', '')
        env['HOME'] = tempfile.gettempdir()
        env['USERPROFILE'] = tempfile.gettempdir()
        env['PYTHONIOENCODING'] = 'utf-8'
        return env
