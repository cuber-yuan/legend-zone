import subprocess
import tempfile
import os
import hashlib

class CppCompiler:
    """
    用于编译和运行C++源代码的工具类。
    """

    def __init__(self, cache_dir=None):
        # 可选：缓存已编译的二进制，避免重复编译
        if cache_dir is None:
            cache_dir = os.path.join(tempfile.gettempdir(), "cpp_code_cache")
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def compile(self, code: str, extra_args=None) -> str:
        """
        编译C++代码，返回可执行文件路径。
        :param code: C++源代码字符串
        :param extra_args: 额外的g++参数（如头文件路径等）
        :return: 可执行文件路径
        """
        code_hash = hashlib.sha256(code.encode('utf-8')).hexdigest()
        exe_path = os.path.join(self.cache_dir, f"cpp_{code_hash}.exe")

        if not os.path.exists(exe_path):
            with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False, encoding='utf-8') as src_file:
                src_file.write(code)
                src_path = src_file.name

            base_dir = os.path.dirname(os.path.abspath(__file__))
            judges_dir = os.path.join(os.path.dirname(base_dir), 'judges')

            args = ['g++', '-std=c++17', src_path, f'-I{base_dir}', f'-I{judges_dir}', '-o', exe_path]
            if extra_args:
                args.extend(extra_args)

            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.remove(src_path)
            if result.returncode != 0:
                raise RuntimeError(f"C++ compile error:\n{result.stderr.decode()}")
        else:
            pass
            # print(f"Using cached executable: {exe_path}")

        return exe_path

    def run(self, exe_path: str, input_str: str = "", timeout=10) -> str:
        """
        运行已编译的可执行文件，返回输出。
        :param exe_path: 可执行文件路径
        :param input_str: 传递给程序的输入
        :param timeout: 超时时间（秒）
        :return: 程序标准输出
        """
        result = subprocess.run(
            [exe_path],
            input=input_str.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(f"C++ runtime error:\n{result.stderr.decode()}")
        return result.stdout.decode()