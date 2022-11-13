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


def remove_parentheses_if_not_bundled(step):
    assert type(step) == str, f"expected type string, but received {type(step)}"
    if step.startswith("("):
        step = step.lstrip("(")
    if step.endswith(")") and len(step.rstrip(")")) > 0:
        if step.rstrip(")")[-1].isdigit():
            return step.rstrip(")") + ")"
        else:
            return step.rstrip(")")
    else:
        return step


def isa_step_to_fact_candidates(step):
    """
    wipe means replace by a whitespace character
    """
    assert type(step) == str, f"expected type string, but received {type(step)}"
    # wipe ML expressions courtesy of lazy matching
    no_ML_expr = re.sub('".+?"', " ", step)
    # escape special characters
    escaped_string_of_special_characters = re.escape("()_'<>^.\\")
    # wipe everything that is not characters usable in fact names
    pattern_for_premise_names = re.compile(f"[^a-zA-Z0-9{escaped_string_of_special_characters}]+")
    clean_step = re.sub(pattern_for_premise_names, " ", no_ML_expr)
    # SH steps cleaning
    clean_step = re.sub("<open>.*?close>"," ",step)
    # split by spaces
    candidates = clean_step.split()
    # remove duplicates
    candidates = list(set(candidates))
    candidates = [remove_parentheses_if_not_bundled(s) for s in candidates]
    if candidates is None:
        candidates = []
    return candidates

def auxiliary_simp_metis_smt_meson_matches(candidates, step):
    if step is None:
        return []
    if any([word in step for word in ["metis", "smt", "add:", "meson", "auto", "unfolding", "using", "by"]]):
        return [remove_parentheses_if_not_bundled(c) for c in candidates]
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
            matches.append(dep)
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

