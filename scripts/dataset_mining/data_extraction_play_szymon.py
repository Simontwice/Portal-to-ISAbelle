import json
import os
import time

from func_timeout import FunctionTimedOut
from smart_open import open

from data_generation_utils import (
    isa_step_to_fact_candidates,
    match_premise_and_deps,
    multiple_thm_deps_attempts,
    match_premise_and_facts_w_statements,
    split_over_suffixes,
    auxiliary_simp_metis_smt_meson_matches,
    get_relative_path,
    extract_assumption_names,
    match_named_premise_w_statements,
)

thm_deps_step = 0
loop_ended_thm_deps = 0
global_facts_step = 0


def single_file_to_data_play_szymon(
        theory_file_path, out_dir, error_log_dir, metadata_log_dir, env, num_attempts=3
):
    file_relative_path, prefix = get_relative_path(theory_file_path)
    proofs = []
    sledgehammer_proofs_on_decrease = []
    sledgehammer_proofs_on_increase = []
    wrong_thm_deps = []

    error_iterator = 0
    error_success = False
    while error_iterator < num_attempts and not error_success:
        try:
            all_steps = env.extract_theory_steps()
            error_success = True

        except (Exception, FunctionTimedOut):
            error_iterator += 1
            time.sleep(300)
            print(f"Error in extract_theory_steps:  , failed {error_iterator} times")

    if not error_success:
        raise NotImplementedError

    prev_state = ""

    for step_num, step in enumerate(all_steps):
        while error_iterator < num_attempts and not error_success:
            try:
                env.clone_to_new_name("default", "prev default")
                error_success = True
            except (Exception, FunctionTimedOut):
                error_iterator += 1
                time.sleep(300)
                print(f"Error in clone_to_new_name:  , failed {error_iterator} times")
        if not error_success:
            raise NotImplementedError

        prev_proof_level = proof_level
        prev_prev_state = prev_state
        prev_state = state
        ######################################################## STEP ##################################################
        error_iterator = 0
        error_success = False
        while error_iterator < num_attempts and not error_success:
            try:
                start = time.time()
                state, rew, done, _ = env.step_to_top_level_state(
                    step, "default", "default"
                )
                end = time.time()
                step_duration = end - start
                if step_duration > 5:
                    print(f"A step took longer than 5s; time taken: {step_duration}, step: {step}")
                error_success = True
            except (Exception, FunctionTimedOut):
                error_iterator += 1
                time.sleep(3)
                print(
                    f"Error: {step} in step_to_top_level_state:  , failed {error_iterator} times, Progress in file: {step_num / len(all_steps)}")
        if not error_success:
            raise NotImplementedError

        error_iterator = 0
        error_success = False
        while error_iterator < num_attempts and not error_success:
            try:
                proof_level = int(env.get_proof_level("default"))
                error_success = True
            except (Exception, FunctionTimedOut):
                error_iterator += 1
                time.sleep(3)
                print(f"Error in get_proof_level:  , failed {error_iterator} times")
        if not error_success:
            raise NotImplementedError
        else:
            if proof_level == 0:
                pass
        breakpoint()


    ########################################### AND WRITE TO FILE #####################################
    with open(
            f'{out_dir}/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
    ) as fp:
        json.dump(proofs, fp, indent=2)

    with open(
            f'{out_dir}_SH_on_decrease/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
    ) as fsh:
        json.dump(sledgehammer_proofs_on_decrease, fsh, indent=2)

    with open(
            f'{out_dir}_SH_on_increase/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
    ) as fsh:
        json.dump(sledgehammer_proofs_on_increase, fsh, indent=2)

    if len(wrong_thm_deps) > 0:
        with open(
                f'{error_log_dir}/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
        ) as fpe:
            json.dump(wrong_thm_deps, fpe, indent=2)

