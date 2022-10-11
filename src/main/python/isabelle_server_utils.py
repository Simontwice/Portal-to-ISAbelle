import subprocess
from time import sleep
import pathlib


def find_pisa_path():
    path = pathlib.Path(__file__)
    while not str(path).endswith("/pisa"):
        path = path.parents[0]
    return path.resolve()

class IsabelleServerTmuxConnection:
    def __init__(self, compile_pisa=True):
        self.used_ports = set()
        self.accessible_ports = [i * 1000 for i in range(8, 15)]
        self.num_trials = 60
        self.compile_pisa = compile_pisa

    def port_to_session(self, port):
        return f"isa_server_{port}"

    def create_local_tmux_session(self, session_name):
        script = f"tmux has-session -t {session_name} || tmux new-session -d -A -s {session_name}"
        subprocess.run(script, shell=True, capture_output=True)

    def kill_local_tmux_session(self, session_name):
        script = f"tmux kill-session -t {session_name}"
        subprocess.run(script, shell=True, capture_output=True)

    def send_command_to_tmux(self, command, session_name):
        script = f"tmux send-keys -t {session_name}:0 '{command}' Enter"
        return subprocess.run(script, shell=True, capture_output=True)

    def read_tmux(self, port):
        return subprocess.run(
            f"tmux capture-pane -t {self.port_to_session(port)}; tmux show-buffer; tmux delete-buffer",
            shell=True,
            capture_output=True,
        ).stdout.decode("utf-8")

    def check_is_running(self, port):
        out = self.read_tmux(port)
        return "Server is running" in out[-100:]

    def check_sbt_compilation(self, port):
        out = self.read_tmux(port)
        return "[success]" in out[-100:]

    def stop_isabelle_server(self, port):
        self.send_command_to_tmux("C-c", self.port_to_session(port))

    def restart_isabelle_server(self, port):
        self.stop_isabelle_server(port)
        sleep(1)
        print(f"server stopped")
        self.send_command_to_tmux(
            f'sbt "runMain pisa.server.PisaOneStageServer{port}"',
            self.port_to_session(port),
        )
        for _ in range(self.num_trials):
            if self.check_is_running(port):
                break
            sleep(1)
        assert self.check_is_running(port)
        # breakpoint()
        print(
            f"Isabelle server restarted. To access: tmux attach-session -t {self.port_to_session(port)}"
        )

    def restart_many_servers(self, ports, stop_previous=True):
        for port in ports:
            self.stop_isabelle_server(port)
        sleep(1)
        for port in ports:
            self.send_command_to_tmux(
                f'sbt "runMain pisa.server.PisaOneStageServer{port}"',
                self.port_to_session(port),
            )
        for _ in range(self.num_trials):
            ports_running = [self.check_is_running(port) for port in ports]
            if all(ports_running):
                break
            sleep(1)
        print(f"Running servers on ports {ports}")

    def start_isabelle_server(self, port):
        print(f"Starting server on port {port}")
        print(f"Check running = {self.check_is_running(port)}")
        if not self.check_is_running(port):
            self.create_local_tmux_session(self.port_to_session(port))
            self.send_command_to_tmux(
                f"cd {find_pisa_path()}", self.port_to_session(port)
            )
            if self.compile_pisa:
                self.send_command_to_tmux("sbt compile", self.port_to_session(port))
                for _ in range(self.num_trials):
                    if self.check_sbt_compilation(port):
                        self.compile_pisa = False
                        break
                    sleep(1)
                assert self.check_sbt_compilation(port)

            self.send_command_to_tmux(
                f'sbt "runMain pisa.server.PisaOneStageServer{port}"',
                self.port_to_session(port),
            )
            for _ in range(self.num_trials):
                port_running = self.check_is_running(port)
                if port_running:
                    break
                sleep(1)
            assert self.check_is_running(port)
            print(
                f"Isabelle server in tmux. To access: tmux attach-session -t {self.port_to_session(port)}"
            )

    def close_isabelle_server(self, port):
        if port not in self.used_ports:
            print(f"Skip, no running session on port {port}.")
        else:
            self.kill_local_tmux_session(self.port_to_session(port))
