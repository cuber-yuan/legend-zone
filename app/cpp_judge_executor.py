import subprocess
import json
import os
from typing import Dict, Any

class CppJudgeExecutor:
    """
    A generic utility for interacting with a C++ executable that communicates
    via JSON over stdin/stdout. This class is agnostic to the JSON content and
    structure.
    """

    def __init__(self, executable_path: str):
        """
        Initialize the executor with the path to the C++ executable.

        Args:
            executable_path: full path to the C++ judge program.

        Raises:
            FileNotFoundError: if no executable exists at the given path.
        """
        self.executable_path = executable_path
        if not os.path.exists(self.executable_path):
            raise FileNotFoundError(
                f"C++ judge executable not found at: {self.executable_path}"
            )

    def run_raw_json(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run one complete interaction with the C++ program.

        It serializes the input Python dict to a JSON string, pipes it to the
        C++ program's standard input, captures the program's standard output,
        and parses it back into a Python dict.

        Args:
            input_data: input data to send to the C++ program (Python dict).

        Returns:
            output data returned by the C++ program (Python dict).

        Raises:
            subprocess.CalledProcessError: if the C++ program exits with a non-zero code.
            json.JSONDecodeError: if the C++ program's output is not valid JSON.
            Exception: other unknown errors raised during execution.
        """
        try:
            # Convert the input dict to a JSON string
            input_json_str = json.dumps(input_data)

            # Run the C++ executable, passing the JSON string to its standard input
            # text=True: handle encoding/decoding automatically
            # check=True: raise if the process returns a non-zero exit code
            # capture_output=True: capture stdout and stderr
            result = subprocess.run(
                [self.executable_path],
                input=input_json_str,
                capture_output=True,
                text=True,
                check=True,
                timeout=2  # Timeout to prevent a hung process
            )

            # Parse the JSON returned by the C++ program on stdout
            output_json = json.loads(result.stdout)
            return output_json

        except subprocess.CalledProcessError as e:
            # If the C++ program crashed, print its stderr to ease debugging
            print(f"Error executing C++ judge. Stderr:\n{e.stderr}")
            raise
        except json.JSONDecodeError as e:
            # If the output is not valid JSON, print it to ease debugging
            print(f"Failed to decode JSON from C++ judge output. Output was:\n{result.stdout}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred while running the C++ judge: {e}")
            raise