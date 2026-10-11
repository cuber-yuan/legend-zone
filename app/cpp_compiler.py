import subprocess
import tempfile
import os
import hashlib

# Bound for the compiled-bot cache. Nothing maps a bot back to its executable
# (the filename is a hash of path + mtime + size), so deleting a bot cannot
# target its builds — only an age cap keeps the directory from growing forever.
MAX_CACHED_BINARIES = 50

class CppCompiler:
    """
    Utility class for compiling and running C++ source code.
    """

    def __init__(self, cache_dir=None):
        # Optional: cache compiled binaries to avoid recompiling
        if cache_dir is None:
            cache_dir = os.path.join(tempfile.gettempdir(), "cpp_code_cache")
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _prune_cache(self):
        """Evict the oldest cached binaries once the cache is over budget.

        Binaries still held by a running match refuse to unlink on Windows;
        those are skipped and picked up by a later compile rather than
        turning a housekeeping step into a bot failure.
        """
        try:
            names = [n for n in os.listdir(self.cache_dir) if n.startswith('cpp_')]
        except OSError:
            return
        if len(names) <= MAX_CACHED_BINARIES:
            return

        dated = []
        for name in names:
            path = os.path.join(self.cache_dir, name)
            try:
                dated.append((os.path.getmtime(path), path))
            except OSError:
                continue
        dated.sort()

        for _, path in dated[:len(dated) - MAX_CACHED_BINARIES]:
            try:
                os.remove(path)
            except OSError:
                continue

    def compile(self, code: str, extra_args=None) -> str:
        """
        Compile C++ code and return the executable path.
        :param code: C++ source code string
        :param extra_args: extra g++ arguments (e.g. include paths)
        :return: executable file path
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
            self._prune_cache()
        else:
            pass
            # print(f"Using cached executable: {exe_path}")

        return exe_path

    def compile_file(self, src_path: str, extra_args=None) -> str:
        """Compile a bot's source file in-place. Cache key includes mtime so
        editing a bot's file invalidates the previous build."""
        stat = os.stat(src_path)
        key = f"{os.path.abspath(src_path)}:{stat.st_mtime_ns}:{stat.st_size}"
        cache_hash = hashlib.sha256(key.encode('utf-8')).hexdigest()
        exe_path = os.path.join(self.cache_dir, f"cpp_{cache_hash}.exe")

        if os.path.exists(exe_path):
            return exe_path

        base_dir = os.path.dirname(os.path.abspath(__file__))
        judges_dir = os.path.join(os.path.dirname(base_dir), 'judges')
        src_dir = os.path.dirname(os.path.abspath(src_path))

        args = ['g++', '-std=c++17', src_path,
                f'-I{base_dir}', f'-I{judges_dir}', f'-I{src_dir}',
                '-o', exe_path]
        if extra_args:
            args.extend(extra_args)

        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(f"C++ compile error:\n{result.stderr.decode()}")
        self._prune_cache()
        return exe_path

    def run(self, exe_path: str, input_str: str = "", timeout=10) -> str:
        """
        Run a compiled executable and return its output.
        :param exe_path: path to the executable
        :param input_str: input passed to the program
        :param timeout: timeout in seconds
        :return: program standard output
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