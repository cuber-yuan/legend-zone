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
        
        sandbox_dir = os.path.dirname(exec_path)
        env = self._get_sandbox_env()

        try:
            result = subprocess.run(
                [exec_path],
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
        finally:
            if os.path.exists(exec_path):
                os.remove(exec_path)

    def _get_sandbox_env(self) -> dict:
        """Create a restricted environment for sandboxed execution."""
        env = {
            'PATH': os.environ.get('PATH', ''),
            'PYTHONPATH': '',
            'HOME': tempfile.gettempdir(),
            'USERPROFILE': tempfile.gettempdir(),
        }
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