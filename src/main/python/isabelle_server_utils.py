import logging
import os
import signal
import subprocess
import time
import pathlib
import psutil

from pisa.src.main.python.PisaFlexibleClient import initialise_env


def find_pisa_path():
    path = pathlib.Path(__file__)
    while not str(path).endswith("/pisa"):
        path = path.parents[0]
    return path.resolve()


class IsabelleServer:
    def __init__(self):
        self.port = 9000
        self.isabelle_pid = None
        self.env = None

    def initialise_env(self, isa_path, theory_file_path):
        self._stop_isabelle_server()
        self.env = self._start_isabelle_server(isa_path, theory_file_path)
        return self.env

    def _start_isabelle_server(self, isa_path, theory_file_path):
        self.env = None
        start_time_single = time.time()
        self._stop_rouge_isabelle_processes()
        if os.path.exists("sbt_ready.txt"):
            os.system("rm sbt_ready.txt")

        sbt_ready = False
        print("starting the server")
        print("deleting sbt bg-jobs folder")
        os.system("rm -rf target/bg-jobs/")
        pwd_orig = os.getcwd()
        pwd = os.getcwd().split("/")
        pwd = f"{'/'.join(pwd[: pwd.index('home') + 2])}/interactive_isabelle/pisa"
        os.chdir(pwd)
        sub = subprocess.Popen(
            'sbt "runMain pisa.server.PisaOneStageServer{0}" | tee sbt_ready.txt'.format(
                self.port
            ),
            shell=True,
        )
        pid = sub.pid
        self.isabelle_pid = pid
        while not sbt_ready:
            print(f"time from start: {time.time() - start_time_single}")
            time.sleep(1)
            if os.path.exists("sbt_ready.txt"):
                with open("sbt_ready.txt", "r") as f:
                    file_content = f.read()
                if (
                    "Server is running. Press Ctrl-C to stop." in file_content
                    and "error" not in file_content
                ):
                    print("sbt should be ready")
                    sbt_ready = True
            if time.time() - start_time_single > 180:
                self._close_sbt_process(pid, verbose=False)
                self._stop_rouge_isabelle_processes()
                os.system("rm sbt_ready.txt")
                raise NotImplementedError
        print(f"Server started with pid {pid}")
        env = initialise_env(
            self.port, isa_path=isa_path, theory_file_path=theory_file_path
        )
        time.sleep(3)
        breakpoint()
        os.chdir(pwd_orig)
        env.post("<initialise>")
        return env

    def _stop_isabelle_server(self):
        if self.isabelle_pid is not None:
            self._close_sbt_process(self.isabelle_pid)
        self._stop_rouge_isabelle_processes()
        print("[stop_isabelle_server] server stopped!")

    def _close_sbt_process(self, isabelle_process_id, verbose=True):
        try:
            parent = psutil.Process(isabelle_process_id)
            children = parent.children(recursive=True)
            for process in children:
                process.send_signal(signal.SIGTERM)
            parent.send_signal(signal.SIGTERM)
            print("[close_sbt_process] Processes killed! ")

        except psutil.NoSuchProcess:
            print("[close_sbt_process] No processes to kill! ")

    def clean_external_prover_memory_footprint(self):
        os.system("ps -ef | grep z3 | awk '{print $2}' | xargs kill -9")
        os.system("ps -ef | grep veriT | awk '{print $2}' | xargs kill -9")
        os.system("ps -ef | grep cvc4 | awk '{print $2}' | xargs kill -9")
        os.system("ps -ef | grep eprover | awk '{print $2}' | xargs kill -9")
        os.system("ps -ef | grep SPASS | awk '{print $2}' | xargs kill -9")
        os.system("ps -ef | grep csdp | awk '{print $2}' | xargs kill -9")

    def _stop_rouge_isabelle_processes(self):
        os.system(
            "ps aux | grep Isabelle | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps aux | grep poly | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps aux | grep sbt | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps -ef | grep scala | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps -ef | grep java | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps -ef | grep polu | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps -ef | grep 'bash sbt' | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
