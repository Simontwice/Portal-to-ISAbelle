import json
import os
import subprocess
import time
import sys
conf_path = os.getcwd()

upper=os.path.join( conf_path, '..' )
upper2 = os.path.join( upper, '..' )
upper3 = os.path.join( upper2, '..' )
upper4 = os.path.join( upper3, '..' )
upper5 = os.path.join( upper4, '..' )

sys.path.append(conf_path)
sys.path.append(upper)
sys.path.append(upper2)
sys.path.append(upper3)
sys.path.append(upper4)
sys.path.append(upper5)


from absl import logging

from pisa.src.main.python.PisaFlexibleClient import initialise_env
from smart_open import open
from tqdm import tqdm
import psutil
import signal


from typing import List
from data_extraction_play_szymon import single_file_to_data_play_szymon


def single_file_on_single_worker(
    theory_file,
    initialised_isa_env,
    out_dir,
    error_log_dir,
    metadata_log_dir,
    isa_process_pid,
):

    failed_init_count = 0
    failed_step_count = 0
    failed_global_facts_count = 0
    failed_thm_deps_count = 0

    failed_files = []
    failed_step_files = []
    failed_init_files = []
    failed_global_facts_files = []
    failed_thm_deps = {}
    failed_step_files_verbose: List[int, List[str, int]] = []
    for num, theory_file_path in tqdm(enumerate([theory_file])):

        theory_file_path = os.path.expanduser(theory_file_path)
        logging.info(
            f"+++++++++++++++++++++++++++++++++++ NEW FILE, NAME: {theory_file_path} +++++++++++++++++++++++++++++++++++++++"
        )
        file_processing_info = single_file_to_data_play_szymon(
            theory_file_path,
            out_dir,
            error_log_dir,
            metadata_log_dir,
            initialised_isa_env,
        )
        if not file_processing_info["successful"]:
            failed_files.append(theory_file_path)
            if file_processing_info["init_failed"]:
                failed_init_count += 1
                failed_init_files.append(theory_file_path)
                # metric_logging.log_scalar(f"failed_init_by_{who_does}", num, file)

            if file_processing_info["step_failed"]:
                failed_step_count += 1
                failed_step_files_verbose.append(
                    file_processing_info["step_failed_info"]
                )
                failed_step_files.append(theory_file_path)
                # metric_logging.log_scalar(f"failed_step_by_{who_does}", num, failed_step_count)

            if file_processing_info["global_facts_failed"]:
                failed_global_facts_count += 1
                failed_global_facts_files.append(theory_file_path)
                # metric_logging.log_scalar(f"failed_global_facts_by_{who_does}", num, failed_global_facts_count)

        if file_processing_info["thm_deps_failed"] is not None:
            failed_thm_deps_lemmas = file_processing_info["thm_deps_failed"]
            failed_thm_deps_count += len(failed_thm_deps_lemmas)
            failed_thm_deps[theory_file_path] = failed_thm_deps_lemmas

        logging.info(f"total failed_init_by: {failed_init_count}")
        logging.info(f"total failed_during_step_by: {failed_step_count}")
        logging.info(f"total failed_global_facts_by: {failed_global_facts_count}")
        logging.info(f"total failed thm_deps_by: {failed_thm_deps_count}")

    with open(
        f"{metadata_log_dir}/mining_info_device_{theory_file.replace('/','.')}", "w"
    ) as f:
        json.dump(file_processing_info, f, indent=2)

    try:
        parent = psutil.Process(isa_process_pid)
        children = parent.children(recursive=True)
        for process in children:
            process.send_signal(signal.SIGTERM)
        parent.send_signal(signal.SIGTERM)
    except psutil.NoSuchProcess:
        pass
    # delete sbt ready txt clean up things just in case
    os.system("rm sbt_ready.txt")
    os.system(
        "ps aux | grep Isabelle | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
    )
    os.system("ps aux | grep poly | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1")
    os.system("ps aux | grep sbt | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1")


class IsaInstance:
    def __init__(self, working_dir=None, isa_path=None, theory_file=None, port=8000):
        assert None not in [isa_path, theory_file, port]
        assert working_dir is None
        self.working_dir = working_dir
        self.isa_path = isa_path
        self.theory_file = theory_file
        self.port = port
        self.env = None
        # Initialize environment
        env = self._initialize()
        if env.successful_starting:
            print("finally successfully initialize the environment")
            self.success_env = True
            self.env = env
        else:
            print("failure initialize the environment")
            self.success_env = False

    def _initialize(self):
        print("Initializing environment")
        print("ISA_PATH: %s" % self.isa_path)
        print("THEORY_FILE: %s" % self.theory_file)
        # print("WORKING_DIR: %s" % self.working_dir) THIS IS DONE AUTOMATICALLY
        env = initialise_env(
            self.port, isa_path=self.isa_path, theory_file_path=self.theory_file
        )
        if env.successful_starting:
            print("Start doing post env initialising environment")
            env.post("<initialise>")
        else:
            print("initialize_env function failed")
        return env


class DataIsaJob:
    def __init__(
        self,
        theory_file_path="/home/szymon/afp-2021-10-22/thys/Sigma_Commit_Crypto/Pedersen.thy",
        isa_path="/home/szymon/Isabelle2021",
        out_dir="gs://n2formal-public-data-europe/simontwice_data/mining_results_dev",
        error_log_dir="gs://n2formal-public-data-europe/simontwice_data/mining_error_log_dev",
        metadata_log_dir="gs://n2formal-public-data-europe/simontwice_data/mining_metadata_log_dev",
        failed_files_dir="gs://n2formal-public-data-europe/simontwice_data/not_initialised_files"
    ):
        self.theory_file_path = theory_file_path
        self.isa_path = os.path.expanduser(isa_path)
        self.out_dir = out_dir
        self.error_log_dir = error_log_dir
        self.metadata_log_dir = metadata_log_dir
        self.failed_files_dir = failed_files_dir
        self.initialised_isa_env, self.isa_pid = self.rev_up_Isabelle_env()

    def execute(self):

        if self.initialised_isa_env is None:
            with open(
                    f'{self.failed_files_dir}/{"_".join(self.theory_file_path.split("/")[-3:])}.json', "w"
            ) as fp:
                json.dump({}, fp)
            return

        single_file_on_single_worker(
            self.theory_file_path,
            self.initialised_isa_env,
            self.out_dir,
            self.error_log_dir,
            self.metadata_log_dir,
            self.isa_pid
        )

    def rev_up_Isabelle_env(self):
        start_time_single = time.time()
        if os.path.exists("sbt_ready.txt"):
            os.system("rm sbt_ready.txt")
        os.system(
            "ps aux | grep Isabelle | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps aux | grep poly | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )
        os.system(
            "ps aux | grep sbt | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
        )

        port = 8000
        sbt_ready = False
        environemnt_success = False
        failure_counter = 0
        while not environemnt_success and failure_counter <= 3:

            print("starting the server")
            print("checking filesystem health")
            os.system("df -h")
            print("deleting sbt bg-jobs folder")
            os.system("rm -rf target/bg-jobs/")
            sub = subprocess.Popen(
                'sbt "runMain pisa.server.PisaOneStageServer{0}" | tee sbt_ready.txt'.format(
                    port
                ),
                shell=True,
            )
            pid = sub.pid
            while not sbt_ready:
                if time.time() - start_time_single > 300:
                    try:
                        parent = psutil.Process(pid)
                        children = parent.children(recursive=True)
                        for process in children:
                            process.send_signal(signal.SIGTERM)
                        parent.send_signal(signal.SIGTERM)
                    except psutil.NoSuchProcess:
                        pass
                    # delete sbt ready txt
                    os.system("rm sbt_ready.txt")
                    os.system(
                        "ps aux | grep Isabelle | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
                    )
                    os.system(
                        "ps aux | grep poly | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
                    )
                    os.system(
                        "ps aux | grep sbt | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
                    )
                    return None, None
                if os.path.exists("sbt_ready.txt"):
                    with open("sbt_ready.txt", "r") as f:
                        file_content = f.read()
                    if (
                        "Server is running. Press Ctrl-C to stop." in file_content
                        and "error" not in file_content
                    ):
                        print("sbt should be ready")
                        sbt_ready = True
            print(f"Server started with pid {pid}")
            time.sleep(3)
            try:
                isa_instance = IsaInstance(
                    isa_path=self.isa_path,
                    theory_file=self.theory_file_path,
                    port=port,
                )
                if isa_instance.success_env:
                    _ = isa_instance.env.initialise_toplevel_state_map()
                    logging.info(
                        f"initialise_env was successful, file: {self.theory_file_path}"
                    )
                    print("escaping the while loop")
                    environemnt_success = True

            except Exception as e:
                print(f"During init an exception occured. Exception text: {e}")
                print("restarting the while loop")
                failure_counter += 1
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for process in children:
                        process.send_signal(signal.SIGTERM)
                    parent.send_signal(signal.SIGTERM)
                except psutil.NoSuchProcess:
                    pass
                # delete sbt ready txt
                os.system("rm sbt_ready.txt")
                os.system(
                    "ps aux | grep Isabelle | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
                )
                os.system(
                    "ps aux | grep poly | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
                )
                os.system(
                    "ps aux | grep sbt | awk '{print $2}' | xargs kill -9 > /dev/null 2>&1"
                )
                sbt_ready = False
                environemnt_success = False
                if time.time() - start_time_single > 300:
                    return None, None
        if not environemnt_success:
            print("environment still cannot be initialized")
            print(
                f"checking single required {time.time() - start_time_single} seconds."
            )
            return None, None
        else:
            print("env init successful!")
            assert isa_instance.env is not None
            return isa_instance.env, pid

job= DataIsaJob()
job.execute()