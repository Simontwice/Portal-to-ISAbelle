import re

from func_timeout import FunctionTimedOut

def get_relative_path(theory_file_path):
    absolute_path = theory_file_path.split("/")
    if "thys" in absolute_path:
        idx = absolute_path.index("thys")
        prefix = "afp:"
    else:
        idx = absolute_path.index("src")
        prefix = "src:"
    return prefix + "/".join(absolute_path[idx + 1 :]).split(".")[0], prefix

def process_match2(match2):
    if match2 is None:
        return None
    else:
        split = match2.split("(-)")
        split = list(filter(lambda x: x is not "", split))
        name, numbers = split[0], split[1:]

        low = int(numbers[0])
        high = int(numbers[1])

        assert low < high, f"low: {low} is not less than high: {high} for string: {match2.group(0)}"
        premise_bundle_numbers = [i for i in range(low, high + 1)]
        return [f"{name}({number})" for number in premise_bundle_numbers]


def process_match3(match3):
    if match3 is None:
        return None
    else:
        split = match3.split("(,)")
        split = list(filter(lambda x: x is not "", split))
        name, numbers = split[0], split[1:]

        assert all(
            [num.isdigit() for num in numbers]
        ), f"not all strings in {numbers} are integers!"
        return [f"{name}({number})" for number in numbers]


def fish_out_actual_premise_names(step):
    assert type(step) == str, f"expected type string, but received {type(step)}"

    escaped_string_of_special_characters = re.escape("_'<>^.\\")
    premise_name_characters = f"[a-zA-Z0-9{escaped_string_of_special_characters}]"

    pattern0 = f"{premise_name_characters}+"
    pattern1 = f"{premise_name_characters}+\([0-9]+\)"
    pattern2 = f"{premise_name_characters}+\([0-9]+\-[0-9]+\)"
    pattern3 = f"{premise_name_characters}+\([0-9]+(,[0-9])+\)"

    match0 = re.search(pattern0, step)
    if match0 is not None:
        match0 = match0.group(0)
    match1 = re.search(pattern1, step)
    if match1 is not None:
        match1 = match1.group(0)
    match2 = re.search(pattern2, step)
    if match2 is not None:
        match2 = match2.group(0)
    match3 = re.search(pattern3, step)
    if match3 is not None:
        match3 = match3.group(0)

    match2 = process_match2(match2)
    match3 = process_match3(match3)

    special_matches = [match for match in [match1, match2, match3] if match is not None]
    num_of_special_matches = len(special_matches)
    if num_of_special_matches > 1:
        print(
            f"component {step} matched more than 1 form of numbered premises! Such as: simps(1), simps(1,4), simps(2-5)!"
        )

    result = []
    if num_of_special_matches == 0:
        # it is a normal name
        if match0 is not None:
            result = [match0]
        else:
            result = []
    else:
        result = [special_matches[0]]
    return result


# def remove_parentheses_if_not_bundled(step):
#     assert type(step) == str, f"expected type string, but received {type(step)}"
#     if step.startswith("("):
#         step = step.lstrip("(")
#     if step.endswith(")") and len(step.rstrip(")")) > 0:
#         if step.rstrip(")")[-1].isdigit():
#             return step.rstrip(")") + ")"
#         else:
#             return step.rstrip(")")
#     else:
#         return step


def isa_step_to_fact_candidates(step):
    """
    wipe means replace by a whitespace character
    """
    assert type(step) == str, f"expected type string, but received {type(step)}"
    # wipe ML expressions courtesy of lazy matching
    no_ML_expr = re.sub('".+?"', " ", step)

    # SH steps cleaning
    clean_step = re.sub("<open>.*?close>", " ", no_ML_expr)

    # escape special characters
    escaped_string_of_special_characters = re.escape("()_'<-,>^.\\")

    # wipe everything that is not characters usable in fact names
    pattern_for_premise_names = re.compile(f"[^a-zA-Z0-9{escaped_string_of_special_characters}]+")
    clean_step = re.sub(pattern_for_premise_names, " ", clean_step)
    clean_step = re.sub("(?<![0-9])[-,]", " ", clean_step)

    # split by spaces
    candidates = clean_step.split()

    # remove duplicates
    candidates = list(set(candidates))

    candidates = sum([fish_out_actual_premise_names(c) for c in candidates],[])
    if candidates is None:
        candidates = []
    return candidates


def auxiliary_simp_metis_smt_meson_matches(candidates, step, force=False):
    if step is None:
        return []
    if force or any(
        [
            word in step
            for word in ["metis", "smt", "add:", "meson", "auto", "unfolding", "using", "by"]
        ]
    ):
        return sum([fish_out_actual_premise_names(c) for c in candidates],[])
    else:
        return []


def isa_step_to_thm_name_for_deps(line):

    if ":" not in line:
        return "<unnamed>"
    uncleaned_theorem = line.split(":")[0]
    no_ML = re.sub('".+?"', " ", uncleaned_theorem)
    no_rewriting = re.sub("\[.+?\]", " ", no_ML)
    no_location = re.sub("\(.+?\)", " ", no_rewriting)
    split = no_location.split()
    if len(split) < 2:
        return "<unnamed>"
    name = split[-1]

    # sometimes it is in a locale, so have to prepend the locale name to the name so Isabelle knows where it's located
    locale_name = None
    if any([substring in line for substring in ["(in ", " in "]]):
        locale_name_with_in = re.search("\( *in *.*? *\)", line)[0]
        locale_name_no_parenth = locale_name_with_in.strip("\(\)").split()
        locale_name = locale_name_no_parenth[locale_name_no_parenth.index("in") + 1]

    return name, locale_name


def multiple_thm_deps_attempts(env, raw_thm_name, context_names):
    """

    Args:
        env: current Isabelle env
        raw_thm_name: raw step containing thm name and statement
        context_names: list of context names seen so far in the file

    Returns: thm_deps, unless times out, then raises FunctionTimedOut

    """
    name, locale_name = isa_step_to_thm_name_for_deps(raw_thm_name)
    possible_names_for_thm_deps = (
        [name, f"{locale_name}.{name}"]
        + [f"{ctxt_name}.{name}" for ctxt_name in context_names]
        + ["END"]
    )
    for name in possible_names_for_thm_deps:
        try:
            thm_deps = env.dependent_theorems(name)
            return thm_deps
        except FunctionTimedOut:
            raise FunctionTimedOut
        except:
            pass
    raise ConnectionAbortedError


def process_raw_global_facts(raw_string):
    if raw_string is None:
        return {}
    list_of_string_tuples = raw_string.split("<SEP>")
    global_fact_dict = {}
    for element in list_of_string_tuples:
        name, definition = element.split("<DEF>")
        global_fact_dict[name] = definition
    return global_fact_dict


def match_premise_and_deps(premise, thm_deps):
    matches = []
    if thm_deps is None:
        return []
    for dep in thm_deps:
        if dep.endswith("." + premise) or dep == premise:
            matches.append(premise)
            break
    return matches


def split_over_suffixes(fact_dict):
    if fact_dict is None:
        return {}
    expanded_fact_dict = {}
    for premise_name, premise_stmt in fact_dict.items():
        split = premise_name.split(".")
        all_suffixes = [".".join(split[-i:]) for i in range(len(split))]
        expanded_fact_dict.update({suff: premise_stmt for suff in all_suffixes})
    return expanded_fact_dict


def match_premise_and_facts_w_statements(premise, fact_dict):
    if fact_dict is None:
        return []
    if premise in fact_dict:
        return [(premise, fact_dict[premise])]
    else:
        return []


def process_raw_thm_deps(raw_thm_deps):
    all_thm_deps = {}
    for entry in raw_thm_deps:
        split = entry.split(".")
        all_suffixes = [".".join(split[-i:]) for i in range(len(split))]
        all_thm_deps.update({suff: entry for suff in all_suffixes})
    return all_thm_deps

