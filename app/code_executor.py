import json
import subprocess
import tempfile
import os
import sys
import shutil
import zipfile
from . import cpp_compiler

class CodeExecutor:
    def __init__(self, code: str, language: str = 'python3', path: str = ""):
        self.code = code
        self.language = language.lower()
        self.exec_file = None  # For C++
        self.path = path

    def run(self, input_str: str) -> str:
        if self.language == 'python3':
            # If path is a .zip file, extract and run __main__.py
            if self.path and self.path.endswith('.zip'):
                return self._run_python_zip(self.path, input_str)
            # Otherwise, run as single file
            return self._run_python(self.code, input_str)
        elif self.language == 'cpp':
            return self._run_cpp(self.code, input_str)
        else:
            raise ValueError(f"Unsupported language: {self.language}")

    # 修改方法签名，接收 code_to_run 参数
    def _run_python(self, code_to_run: str, input_str: str) -> str:
        with tempfile.TemporaryDirectory() as sandbox_dir:
            temp_path = os.path.join(sandbox_dir, 'solution.py')
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(code_to_run)

            try:
                env = self._get_sandbox_env()
                result = subprocess.run(
                    [sys.executable, "-u", temp_path],
                    input=input_str.encode('utf-8'),
                    capture_output=True,
                    timeout=10,
                    check=True,
                    cwd=sandbox_dir,
                    env=env
                )
                return result.stdout.decode('utf-8')
            except subprocess.CalledProcessError as e:
                error_message = f"Bot code exited with error code {e.returncode}.\n" \
                                f"--- STDOUT ---\n{e.stdout.decode('utf-8')}\n" \
                                f"--- STDERR ---\n{e.stderr.decode('utf-8')}"
                print(error_message)
                raise RuntimeError(f"Bot execution failed. See server logs for details.")
            except subprocess.TimeoutExpired:
                raise RuntimeError("Python code execution timed out")

    # 修改方法签名以保持一致性（虽然逻辑不变）
    def _run_cpp(self, code_to_run: str, input_json: str) -> str:
        compiler = cpp_compiler.CppCompiler()
        exec_path = compiler.compile(code_to_run)

        # Copy to temp location to avoid Windows file locking issues
        with tempfile.TemporaryDirectory() as sandbox_dir:
            temp_exec = os.path.join(sandbox_dir, os.path.basename(exec_path))
            shutil.copy2(exec_path, temp_exec)

            env = self._get_sandbox_env()

            try:
                result = subprocess.run(
                    [temp_exec],
                    input=input_json.encode(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    cwd=sandbox_dir,
                    env=env
                )

                if result.returncode != 0:
                    raise RuntimeError(f"C++ runtime error: {result.stderr.decode()}")

                return result.stdout.decode()
            except subprocess.TimeoutExpired:
                raise RuntimeError("C++ execution timed out")

    def _get_sandbox_env(self) -> dict:
        """Create a restricted environment for sandboxed execution.

        Start from a clean copy of the parent environment so that installed
        third-party packages (e.g. numpy) remain importable, then override the
        entries that should be isolated. Setting PYTHONPATH to an empty string
        would hide the site-packages directory and break `import numpy` and
        friends, so it is deliberately left untouched here.
        """
        env = dict(os.environ)
        env['PATH'] = os.environ.get('PATH', '')
        env['HOME'] = tempfile.gettempdir()
        env['USERPROFILE'] = tempfile.gettempdir()
        # Force UTF-8 for the child Python's stdin/stdout/stderr so that bots
        # running on Windows (where the default codec is GBK/cp936) still emit
        # bytes that this server can decode. Without this, `print("中文")` and
        # `print(json.dumps(..., ensure_ascii=False))` would crash the match.
        env['PYTHONIOENCODING'] = 'utf-8'
        return env


    ## TODO modify this method to handle zip files
    def _run_python_zip(self, zip_path: str, input_str: str) -> str:
        with tempfile.TemporaryDirectory() as sandbox_dir:
            extract_dir = os.path.join(sandbox_dir, 'extracted')
            os.makedirs(extract_dir)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                self._safe_extract_zip(zip_ref, extract_dir)
            
            main_path = os.path.join(extract_dir, '__main__.py')
            if not os.path.exists(main_path):
                raise RuntimeError("__main__.py not found in zip archive")
            
            try:
                env = self._get_sandbox_env()
                result = subprocess.run(
                    [sys.executable, "-u", main_path],
                    input=input_str.encode('utf-8'),
                    capture_output=True,
                    timeout=10,
                    check=True,
                    cwd=extract_dir,
                    env=env
                )
                return result.stdout.decode('utf-8')
            except subprocess.CalledProcessError as e:
                error_message = f"Bot code exited with error code {e.returncode}.\n" \
                                f"--- STDOUT ---\n{e.stdout.decode('utf-8')}\n" \
                                f"--- STDERR ---\n{e.stderr.decode('utf-8')}"
                print(error_message)
                raise RuntimeError(f"Bot execution failed. See server logs for details.")
            except subprocess.TimeoutExpired:
                raise RuntimeError("Python code execution timed out")

    def _safe_extract_zip(self, zip_ref, extract_dir):
        """Safely extract zip file, preventing Zip Slip attacks."""
        extract_dir = os.path.realpath(extract_dir)
        
        for member in zip_ref.namelist():
            member_path = os.path.realpath(os.path.join(extract_dir, member))
            if not member_path.startswith(extract_dir):
                raise ValueError(f"Zip Slip attack detected: {member}")
        
        zip_ref.extractall(extract_dir)