import json
import os
import time

from absl import logging
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
    theory_file_path, out_dir, error_log_dir, metadata_log_dir, env
):
    file_relative_path, prefix = get_relative_path(theory_file_path)
    proofs_key = f"{prefix}:{file_relative_path}"
    file_processing_info = {
        "init_failed": False,
        "post_init_failed": False,
        "step_failed": False,
        "step_failed_info": False,
        "global_facts_failed": False,
        "thm_deps_failed": None,
        "successful": False,
    }
    proofs = []
    sledgehammer_proofs = []
    wrong_thm_deps = []

    try:
        all_steps = env.extract_theory_steps()

    except (Exception, FunctionTimedOut) as e:
        file_processing_info["init_failed"] = True
        logging.info(f"did not manage to env.extract_theory_steps, error: {e}")
        return file_processing_info

    proof_open = False
    proof_level = 0
    prev_proof_level = 0
    state = None

    context_names = ["EMPTY"]

    if len(all_steps) <= 5:
        # files this short do not concern us
        return file_processing_info

    current_proof = {
        "statement": None,
        "transitions": [],
        "local_facts": {},
        "assumptions": {},
        "named_assumptions": {},
    }
    current_proof_sledgehammer = {
        "statement": None,
        "transitions": [],
        "local_facts": {},
        "assumptions": {},
        "named_assumptions": {},
    }

    prev_state = ""

    for step_num, step in enumerate(all_steps):
        global thm_deps_step
        if step.startswith(
            "context "
        ):  # this is some magic in case thm_deps fails when called normally
            step_split = step.split()
            context_names.append(step_split[step_split.index("context") + 1])

        if proof_open and not step.startswith("text"):

            possible_premises = isa_step_to_fact_candidates(step)
            current_proof["transitions"].append(
                {
                    "state": state,
                    "prev_state": prev_state,
                    "prev_step": all_steps[step_num-1] if proof_level>0 else "",
                    "step": step,
                    "possible_premises": possible_premises,
                    "premises_without_statements": None,
                    "definitions": list(
                        filter(lambda x: x.endswith("_def"), possible_premises)
                    ),
                    "premises": [],
                    "proof_level": proof_level,
                }
            )

        env.clone_to_new_name("default", "prev default")
        prev_proof_level = proof_level
        prev_prev_state = prev_state
        prev_state = state
        ######################################################## STEP ##################################################
        try:
            start = time.time()
            state, rew, done, _ = env.step_to_top_level_state(
                step, "default", "default"
            )
            end = time.time()
            step_duration = end - start
            if step_duration > 5:
                logging.info(
                    f"A step took longer than 5s; time taken: {step_duration}, step: {step}"
                )

        except Exception as e:
            logging.info(
                f"A step in file {theory_file_path} has failed! Step: {step}, Progress in file: {step_num/len(all_steps)}, error: {e}"
            )
            file_processing_info["step_failed"] = True
            file_processing_info["step_failed_info"] = (
                step_num,
                (step, len(all_steps)),
            )
            return file_processing_info

        proof_level = int(env.get_proof_level("default"))
        finished_subproof = proof_level < prev_proof_level

        ############################################### SLEDGEHAMMER STEP ##############################################
        if finished_subproof:
            # SH step time
            try:
                state_sh, rew, done, _ = env.step_to_top_level_state(
                    "sledgehammer", "prev default", "sh_default"
                )
            except (Exception, FunctionTimedOut) as e:
                state_sh = 'failure due to time out'
                print('a sledgehammer step timed out, proceed as sledgehammer failure')

            os.system("ps -ef | grep z3 | awk '{print $2}' | xargs kill -9")
            os.system("ps -ef | grep veriT | awk '{print $2}' | xargs kill -9")
            os.system("ps -ef | grep cvc4 | awk '{print $2}' | xargs kill -9")
            os.system("ps -ef | grep eprover | awk '{print $2}' | xargs kill -9")
            os.system("ps -ef | grep SPASS | awk '{print $2}' | xargs kill -9")

            hammer_time_success = state_sh.startswith("by ")
            if hammer_time_success:
                hammer_step = state_sh.split("<hammer>")[0]
                premises_without_statements_hammer = (
                    auxiliary_simp_metis_smt_meson_matches(
                        isa_step_to_fact_candidates(hammer_step), hammer_step
                    )
                )
                current_proof_sledgehammer["transitions"].append(
                    {
                        "step": hammer_step,
                        "prev_step": all_steps[step_num-1] if prev_proof_level>0 else "",
                        "state": prev_state,
                        "prev_state": prev_prev_state,
                        "premises_without_statements": premises_without_statements_hammer,
                        "definitions": list(
                            filter(
                                lambda x: x.endswith("_def"),
                                premises_without_statements_hammer,
                            )
                        ),
                        "premises": [],
                        "proof_level": prev_proof_level,
                    }
                )

        if not proof_open:
            # means we just started the proof, this step was the lemma statement
            if proof_level > 0:
                proof_open = True
                assert current_proof["statement"] is None
                current_proof["statement"] = step
                current_proof_sledgehammer["statement"] = step
                raw_statement_for_thm_deps = step
        else:
            if proof_level == 0:
                thm_deps_step += 1
                proof_open = False
                ################################################## LOCAL FACTS #################################################

                local_facts = env.dataset_extraction_local_facts(
                    isabelle_state="prev default"
                )
                local_facts_accelerated = split_over_suffixes(local_facts)
                statement = current_proof["statement"]
                named_assumptions = extract_assumption_names(str(statement))
                current_proof["local_facts"] = {
                    **current_proof["local_facts"],
                    **local_facts,
                }
                current_proof_sledgehammer["local_facts"] = {
                    **current_proof_sledgehammer["local_facts"],
                    **local_facts,
                }
                assms = {
                    name: statement
                    for name, statement in local_facts.items()
                    if "assms" in name
                }
                named_assumptions_dict = dict(
                    sum(
                        [
                            match_named_premise_w_statements(
                                premise, local_facts_accelerated
                            )
                            for premise in named_assumptions
                        ],
                        [],
                    )
                )
                current_proof["assumptions"] = assms
                current_proof["named_assumptions"] = named_assumptions_dict
                current_proof_sledgehammer["assumptions"] = assms
                current_proof_sledgehammer["named_assumptions"] = named_assumptions_dict

                ################################################## THM DEPS ############################################
                logging.info(f"Trying to extract thm_deps")
                start = time.time()
                try:
                    thm_deps = multiple_thm_deps_attempts(
                        env, raw_statement_for_thm_deps, context_names
                    )
                    logging.info(
                        f"managed theorem deps! name: {raw_statement_for_thm_deps.split(':')[0]}"
                    )
                    # metric_logging.log_scalar("thm_deps", thm_deps_step, value=1)
                    if thm_deps_step % 50 == 0:
                        logging.info(f"Thm deps: {thm_deps}"[-20:])
                except Exception as e:
                    wrong_thm_deps.append(f"{proofs_key}: {raw_statement_for_thm_deps}")
                    # metric_logging.log_scalar("thm_deps", thm_deps_step, value=0)
                    thm_deps = []
                    logging.info(
                        f"my guy did not manage to extract thm_deps; {proofs_key}: {raw_statement_for_thm_deps}, error: {e}"
                    )
                end = time.time()
                thm_deps_time = end - start
                if thm_deps_time > 0.2:
                    logging.info(
                        f"Thm_deps extraction attempt took: ~ {thm_deps_time} s"
                    )
                # metric_logging.log_scalar("thm_deps_time", thm_deps_step, value=thm_deps_time)

                ################################## END OF PROOF THM DEPS TO STEP MATCHING ##############################
                for t_num, transition in enumerate(current_proof["transitions"]):
                    transition["premises_without_statements"] = []
                    auxiliary_matches = auxiliary_simp_metis_smt_meson_matches(
                        transition["possible_premises"], transition["step"]
                    )
                    for premise in transition["possible_premises"]:
                        premise_deps_match = match_premise_and_deps(premise, thm_deps)
                        transition["premises_without_statements"] += premise_deps_match
                    transition["premises_without_statements"] = list(
                        set(
                            transition["premises_without_statements"]
                            + auxiliary_matches
                        )
                    )
                proofs.append(current_proof)
                sledgehammer_proofs.append(current_proof_sledgehammer)
                del current_proof
                del current_proof_sledgehammer

                current_proof = {
                    "statement": None,
                    "transitions": [],
                    "local_facts": {},
                    "assumptions": {},
                    "named_assumptions": {},
                }
                current_proof_sledgehammer = {
                    "statement": None,
                    "transitions": [],
                    "local_facts": {},
                    "assumptions": {},
                    "named_assumptions": {},
                }
                prev_prev_state = ""
                prev_state = ""

        if (
            len(all_steps) - step_num == 5
        ):  # if we're near the end, call global facts. When called at the very end, it often fails
            ########################################## GLOBAL FACTS EXTRACTION #########################################
            global global_facts_step
            global_facts_step += 1
            start = time.time()

            logging.info(f"Trying to obtain global facts")
            try:
                global_facts = env.dataset_extraction_global_facts(
                    isabelle_state="default"
                )
                global_facts_accelerated = split_over_suffixes(global_facts)
                # metric_logging.log_scalar("all_facts", global_facts_step, value=1)
                logging.info(f"Global facts extracted!")

            except Exception as e:
                # metric_logging.log_scalar("all_facts", global_facts_step, value=0)
                logging.info(
                    f"Failed to extract global facts in file {theory_file_path}, error: {e}"
                )
                file_processing_info["global_facts_failed"] = True
                return file_processing_info

            end = time.time()
            logging.info(f"The global facts extraction took: {end - start} seconds")
            # metric_logging.log_scalar("global_facts_time", thm_deps_step, value=end - start)

    ########################################### PREMISES TO STATEMENTS MATCHING ########################################
    for proof in proofs:
        local_facts_accelerated = split_over_suffixes(proof["local_facts"])
        global_and_local_facts_accelerated = {
            **global_facts_accelerated,
            **local_facts_accelerated,
        }
        for transition in proof["transitions"]:
            total_stuff_to_check = (
                transition["premises_without_statements"] + transition["definitions"]
            )
            for premise in total_stuff_to_check:
                premise_and_statement_list = match_premise_and_facts_w_statements(
                    premise, global_and_local_facts_accelerated
                )
                transition["premises"] += premise_and_statement_list
            transition["premises"] = dict(set(transition["premises"]))

    for sh_proof in sledgehammer_proofs:
        local_facts_accelerated_sh = split_over_suffixes(sh_proof["local_facts"])
        global_and_local_facts_accelerated_sh = {
            **global_facts_accelerated,
            **local_facts_accelerated_sh,
        }
        for sh_transition in sh_proof["transitions"]:
            total_stuff_to_check_sh = (
                sh_transition["premises_without_statements"]
                + sh_transition["definitions"]
            )
            for sh_premise in total_stuff_to_check_sh:
                premise_and_statement_list_sh = match_premise_and_facts_w_statements(
                    sh_premise, global_and_local_facts_accelerated_sh
                )
                sh_transition["premises"] += premise_and_statement_list_sh
            sh_transition["premises"] = dict(set(sh_transition["premises"]))

    ########################################### AND WRITE TO FILE #####################################
    with open(
        f'{out_dir}/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
    ) as fp:
        json.dump(proofs, fp, indent=2)

    with open(
        f'{out_dir}_SH/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
    ) as fsh:
        json.dump(sledgehammer_proofs, fsh, indent=2)

    with open(
        f'{metadata_log_dir}/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
    ) as fp:
        json.dump(file_processing_info, fp, indent=2)

    if len(wrong_thm_deps) > 0:
        with open(
            f'{error_log_dir}/{"_".join(file_relative_path.split("/")[-3:])}.json', "w"
        ) as fpe:
            json.dump(wrong_thm_deps, fpe, indent=2)

    file_processing_info["successful"] = True
    return file_processing_info
