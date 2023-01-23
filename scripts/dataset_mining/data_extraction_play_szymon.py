import json
import os
import time
from collections import defaultdict
from typing import Dict, List, Optional

from func_timeout import FunctionTimedOut
from smart_open import open
from smart_open import smart_open
from pisa.src.main.python.PisaFlexibleClient import (
    AvailableFactsTimeout,
    EmptyInitialStateException,
    EnvInitFailedException,
    InitFailedException,
    ProceedToLineFailedException,
)
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
        theory_file_path, out_dir, error_log_dir, metadata_log_dir, env, num_attempts=3,i=-1
):
    start = time.time()
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
    facts ={}
    for step_num, step in enumerate(all_steps):
        try:
            state, rew, done, _ = env.step_to_top_level_state(
                step, "default", "default"
            )
            proof_level = int(env.get_proof_level())
            if proof_level>0:
                facts = env.all_facts_processed()
                process_facts(env,available_facts=facts, problem_key=i,lemma="<lemmaname>",relative_path="<relpath>")
                break
        except (Exception, FunctionTimedOut):
            error_iterator += 1

    # lemma = list(filter(lambda x: x.startswith("theorem "), all_steps))[0]
    # out = {"path":theory_file_path, "theorem":lemma}
    # ########################################### AND WRITE TO FILE #####################################
    # with open(
    #         f'minif2f_tt/{i}.json', "w"
    # ) as fp:
    #     json.dump(out, fp, indent=2)
    # end = time.time()
    # print(f"This took {end-start} seconds")


def process_facts(env, available_facts, problem_key, lemma, relative_path):
    data = {}
    data["problem_key"] = problem_key
    data["lemma"] = lemma
    data["relative_path"] = relative_path
    try:
        # First trim and clear premises names and stmts.
        for fact_name, fact in available_facts.items():
            fact_name = trim_string(fact_name)
            fact = trim_string(fact)
            if fact[:5] == "test ":
                fact = fact[5:]
            available_facts[fact_name] = fact
        # First get locals ~ stmts might be repeated... locals are likely to be more useful.
        # Keep only unique stmts
        seen_stmts = set()
        unique_available_facts = dict()
        for fact_name, fact in available_facts.items():
            if fact_name.startswith("local.") and (fact not in seen_stmts):
                unique_available_facts[fact_name] = fact
                seen_stmts.add(fact)
        for fact_name, fact in available_facts.items():
            if (not fact_name.startswith("local.")) and (fact not in seen_stmts):
                unique_available_facts[fact_name] = fact
                seen_stmts.add(fact)

        available_facts = unique_available_facts

        data["fact_name_to_pisa_names"] = {}

        (
            premise_name_to_pisa_names,
            unsuccessful_premises_names,
        ) = translate_premise_names_to_pisa_names(
            env, available_facts
        )
        unsuccessful_premises_names = set(unsuccessful_premises_names)
        data["fact_name_to_pisa_names"] = premise_name_to_pisa_names
        if len(unsuccessful_premises_names) == 0:
            available_facts_final = available_facts
        else:
            available_facts_final = {}
            for fact_name, fact in available_facts.items():
                if fact_name in unsuccessful_premises_names:
                    continue
                available_facts_final[fact_name] = fact
        data["available_facts"] = available_facts_final
        data["num_unavailable_facts"] = len(unsuccessful_premises_names)
        data["num_available_facts"] = len(available_facts_final)
    except NotImplementedError:
        data["error"] = "Available facts extraction error"
    except FunctionTimedOut:
        data["error"] = "Function timed out"
    except EnvInitFailedException:
        data["error"] = "Env init failed"
    except ProceedToLineFailedException:
        data["error"] = "Proceed to line failed"
    except EmptyInitialStateException:
        data["error"] = "Empty initial state"
    except InitFailedException:
        data["error"] = "Initialisation failed"
    except AvailableFactsTimeout:
        data["error"] = "Available facts timeout"
    finally:
        with smart_open(f"gs://n2formal-public-data-europe/datasets_mm/2023_01_21_pisa_available_facts_minif2f/problem_{problem_key}.json", "w") as fp:
            json.dump(data, fp=fp, sort_keys=True, indent=2)


def trim_string(input_string):
    return " ".join(input_string.replace("\n", " ").split())

def translate_premise_names_to_pisa_names(env, premises_names: List[str]):
    premise_name_to_pisa_names: Dict[str, List[str]] = defaultdict(list)
    unsuccessful_premises_names: List[str] = []

    for premise in premises_names:
        possible_premise_names = []
        suffix = premise.split("_")[-1]
        prefix = premise.rsplit("_", 1)[0]

        if suffix.isdigit():
            premise_alternative = f"{prefix}({suffix})"
            possible_premise_names.append(premise_alternative)
            possible_premise_names.append(premise)
        else:
            possible_premise_names.append(premise)

        isa_steps = [f"using {premise}" for premise in possible_premise_names]
        step_successful = False

        for step in isa_steps:
            next_proof_state, _, done, _ = env.step_to_top_level_state(
                step,
                "default",
                -1,
            )

            next_proof_state_clean = trim_string_optional(next_proof_state)
            step_correct = True
            for prefix_error in [
              "Step error: Undefined fact", "Step error: Bad fact", "Step error: Inaccessible fact"
            ]:
                if prefix_error in next_proof_state_clean:
                    print(f"FAILURE: {next_proof_state_clean}, premise: {premise}")
                    step_correct = False
                    break

            if step_correct:
                pisa_name = step.split()[-1]
                premise_name_to_pisa_names[premise].append(pisa_name)
                step_successful = True
        if not step_successful:
            unsuccessful_premises_names.append(premise)

    return premise_name_to_pisa_names, unsuccessful_premises_names

def trim_string_optional(input_string: Optional[str]) -> Optional[str]:
    if input_string is None:
        return None
    return " ".join(input_string.replace("\n", " ").split()).strip()