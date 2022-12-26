import json
import os
import time

from func_timeout import FunctionTimedOut
from smart_open import open

from data_generation_utils import (
    get_relative_path,
)

thm_deps_step = 0
loop_ended_thm_deps = 0
global_facts_step = 0


def single_file_to_data_play_szymon(
        theory_file_path, out_dir, error_log_dir, metadata_log_dir, env, num_attempts=3
):
    file_relative_path, prefix = get_relative_path(theory_file_path)
    file_processing_info = {
        "init_failed": False,
        "post_init_failed": False,
        "step_failed": False,
        "step_failed_info": False,
        "global_facts_failed": False,
        "thm_deps_failed": None,
        "successful": False,
    }

    error_iterator = 0
    error_success = False
    #extract theory steps
    while error_iterator < num_attempts and not error_success:
        try:
            all_steps = env.extract_theory_steps()
            error_success = True

        except (Exception, FunctionTimedOut):
            error_iterator += 1
            time.sleep(300)
            print(f"Error in extract_theory_steps:  , failed {error_iterator} times")
    if not error_success:
        file_processing_info["init_failed"] = True
        print(f"did not manage to env.extract_theory_steps, error:  ")
        return file_processing_info

    proof_was_open_before_step = False
    proof_level = 0
    non_proof_steps = []

    if len(all_steps) <= 5:
        # files this short do not concern us
        return file_processing_info


    for step_num, step in enumerate(all_steps):
        ######################################################## STEP ##################################################
        error_iterator = 0
        error_success = False
        #step
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
                time.sleep(300)
                print(
                    f"Error: {step} in step_to_top_level_state:  , failed {error_iterator} times, Progress in file: {step_num / len(all_steps)}")
        if not error_success:
            file_processing_info["step_failed"] = True
            file_processing_info["step_failed_info"] = (
                step_num,
                (step, len(all_steps)),
            )
            return file_processing_info

        error_iterator = 0
        error_success = False
        #get_proof_level
        while error_iterator < num_attempts and not error_success:
            try:
                proof_level = int(env.get_proof_level("default"))
                error_success = True
            except (Exception, FunctionTimedOut):
                error_iterator += 1
                time.sleep(300)
                print(f"Error in get_proof_level:  , failed {error_iterator} times")
        if not error_success:
            file_processing_info["get_proof_level_failed"] = True
            print(f"did not manage to get_proof_level, error:  ")
            return file_processing_info

        if not proof_was_open_before_step:
            if proof_level == 0:
                non_proof_steps.append(step)
            # means we just started the proof, this step was the lemma statement
            else:
                proof_was_open_before_step = True
                non_proof_steps.append(step)

        else:
            if proof_level == 0:
                proof_was_open_before_step = False


    ########################################### AND WRITE TO FILE #####################################
    non_proof_text = "<proof_step_sep>".join(non_proof_steps)
    non_proof_text = json.dumps(non_proof_text)
    breakpoint()
    with open(
            f'{out_dir}/{"_".join(file_relative_path.split("/")[-3:])}_non_proof_steps.json', "w"
    ) as fp:
        json.dump(non_proof_text, fp, indent=2)

    with open(
            f'{metadata_log_dir}/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
    ) as fp:
        json.dump(file_processing_info, fp, indent=2)

    file_processing_info["successful"] = True
    return file_processing_info
