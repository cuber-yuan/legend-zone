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
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            # 直接使用传入的参数进行写入
            f.write(code_to_run)
            temp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, "-u", temp_path],
                input=input_str.encode('utf-8'),
                capture_output=True,
                timeout=10, # 5-second timeout
                check=True # This will raise CalledProcessError on non-zero exit codes
            )
            return result.stdout.decode('utf-8')
        except subprocess.CalledProcessError as e:
            # 修改这里，打印更详细的错误信息到服务器控制台
            error_message = f"Bot code exited with error code {e.returncode}.\n" \
                            f"--- STDOUT ---\n{e.stdout.decode('utf-8')}\n" \
                            f"--- STDERR ---\n{e.stderr.decode('utf-8')}"
            print(error_message) # 在服务器后台打印详细错误
            raise RuntimeError(f"Bot execution failed. See server logs for details.")
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Python code execution timed out")
        finally:
            os.remove(temp_path)

    # 修改方法签名以保持一致性（虽然逻辑不变）
    def _run_cpp(self, code_to_run: str, input_json: str) -> str:
        compiler = cpp_compiler.CppCompiler()
        path = compiler.compile(code_to_run)


        # 运行
        result = subprocess.run(
            [path],
            input=input_json.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )

        if result.returncode != 0:
            raise RuntimeError(f"C++ runtime error: {result.stderr.decode()}")

        return result.stdout.decode()


    ## TODO modify this method to handle zip files
    def _run_python_zip(self, zip_path: str, input_str: str) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract zip to temp_dir
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            main_path = os.path.join(temp_dir, '__main__.py')
            if not os.path.exists(main_path):
                raise RuntimeError("__main__.py not found in zip archive")
            try:
                result = subprocess.run(
                    [sys.executable, "-u", main_path],
                    input=input_str.encode('utf-8'),
                    capture_output=True,
                    timeout=10,
                    check=True
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