import json
import os

from absl import logging
from pisa.src.main.python.isabelle_server_utils import IsabelleServerTmuxConnection
from smart_open import open
from tqdm import tqdm

import metric_logging
from typing import Tuple
from data_extraction_play_szymon import single_file_to_data_play_szymon


def many_files_on_single_worker(
    ds_split_path,
    isa_path,
    port,
    device_id,
    split_id,
    out_dir,
    error_log_dir,
    metadata_log_dir,
    isa_tmux,
):
    thy_split_name = ds_split_path.split("/")[-1]
    with open(
        ds_split_path,
        "r",
    ) as f:
        files_database = json.load(f)

    who_does = f"device_{device_id} - split_{split_id}"
    failed_init_count = 0
    failed_step_count = 0
    failed_global_facts_count = 0
    failed_thm_deps_count = 0
    files_to_do = files_database[f"device_id_{device_id}"][f"split_id_{split_id}"]
    logging.info(f"N. files to process: {len(files_to_do)}")

    failed_files = []
    failed_step_files = []
    failed_init_files = []
    failed_global_facts_files = []
    failed_thm_deps = {}
    failed_step_files_verbose: Tuple[int, Tuple[str, int]] = []
    for num, file in tqdm(enumerate(files_to_do[6531:])):

        logging.info("Restarting isa server")
        isa_tmux.restart_isabelle_server(port)
        file = os.path.expanduser(file)
        logging.info(
            f"+++++++++++++++++++++++++++++++++++ NEW FILE, NAME: {file} +++++++++++++++++++++++++++++++++++++++"
        )
        file_processing_info = single_file_to_data_play_szymon(
            port, file, out_dir, error_log_dir, metadata_log_dir, isa_path
        )
        if not file_processing_info["successful"]:
            failed_files.append(file)
            if file_processing_info["init_failed"]:
                failed_init_count += 1
                failed_init_files.append(file)
                # metric_logging.log_scalar(f"failed_init_by_{who_does}", num, file)

            if file_processing_info["step_failed"]:
                failed_step_count += 1
                failed_step_files_verbose.append(file_processing_info["step_failed_info"])
                failed_step_files.append(file)
                # metric_logging.log_scalar(f"failed_step_by_{who_does}", num, failed_step_count)

            if file_processing_info["global_facts_failed"]:
                failed_global_facts_count += 1
                failed_global_facts_files.append(file)
                # metric_logging.log_scalar(f"failed_global_facts_by_{who_does}", num, failed_global_facts_count)

        if file_processing_info["thm_deps_failed"] is not None:
            failed_thm_deps_lemmas = file_processing_info["thm_deps_failed"]
            failed_thm_deps_count += len(failed_thm_deps_lemmas)
            failed_thm_deps[file] = failed_thm_deps_lemmas

        logging.info(
            f"processed by {who_does} : {num} of {len(files_to_do)} = {100 * num / len(files_to_do)} %"
        )
        logging.info(f"total failed_init_by_{who_does}: {failed_init_count}")
        logging.info(f"total failed_during_step_by_{who_does}: {failed_step_count}")
        logging.info(f"total failed_global_facts_by_{who_does}: {failed_global_facts_count}")
        logging.info(f"total failed thm_deps_by_{who_does}: {failed_thm_deps_count}")

    with open(f"{metadata_log_dir}/mining_info_device_{device_id}_{thy_split_name}", "w") as f:
        json.dump(file_processing_info, f, indent=2)



class DataIsaJob(Job):
    def __init__(
        self,
        ds_split_path="first_split.json",
        isa_path="~/Isabelle2021",
        out_dir="gs://n2formal-public-data-europe/simontwice_data/mining_results_dev",
        error_log_dir="gs://n2formal-public-data-europe/simontwice_data/mining_error_log_dev",
        metadata_log_dir="gs://n2formal-public-data-europe/simontwice_data/mining_metadata_log_dev",
        device_id=0,
    ):
        super().__init__()
        self.ds_split_path = ds_split_path
        self.isa_path = os.path.expanduser(isa_path)
        self.out_dir = out_dir
        self.error_log_dir = error_log_dir
        self.metadata_log_dir = metadata_log_dir
        self.isa_tmux = IsabelleServerTmuxConnection(True)
        self.device_id = device_id
        self.ports = [8000]

        for port in self.ports:
            self.isa_tmux.start_isabelle_server(port)

        metric_logging.log_scalar("device_id", 0, device_id)

    def execute(self):
        many_files_on_single_worker(
            self.ds_split_path,
            self.isa_path,
            self.ports[0],
            self.device_id,
            0,
            self.out_dir,
            self.error_log_dir,
            self.metadata_log_dir,
            self.isa_tmux,
        )
