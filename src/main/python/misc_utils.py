from typing import Optional



def trim_string_optional(input_string: Optional[str]) -> Optional[str]:
    if input_string is None:
        return None
    return " ".join(input_string.replace("\n", " ").split()).strip()


def is_sus(premise_name):
    return premise_name.split("_")[-1].isdigit()

def process_raw_facts(raw_string):
    if raw_string == "":
        return {}
    if (
            raw_string
            == 'de.unruh.isabelle.control.IsabelleException: exception UNDEF raised (line 183 of "Isar/toplevel.ML")'
    ):
        raise NotImplementedError
    list_of_string_tuples = raw_string.split("<SEP>")
    global_fact_dict = {}
    for element in list_of_string_tuples:
        name, definition = element.split("<DEF>")
        global_fact_dict[name] = definition

    return global_fact_dict

def process_raw_global_facts(raw_string):
    if raw_string == "":
        return {}
    if (
        raw_string
        == 'de.unruh.isabelle.control.IsabelleException: exception UNDEF raised (line 183 of "Isar/toplevel.ML")'
    ):
        raise NotImplementedError
    list_of_string_tuples = raw_string.split("<SEP>")
    global_fact_dict = {}
    for element in list_of_string_tuples:
        name, definition = element.split("<DEF>")
        isabelle_possible_names = premise_name_to_possible_isabelle_formats(name)
        for possible_name in isabelle_possible_names:
            global_fact_dict[possible_name] = definition

    return global_fact_dict


def premise_name_to_possible_isabelle_formats(premise_name):
    """
    DEPRECATED, JOB TAKEN OVER BY "CHECK IF TRANSLATE_PREMISE_NAMES
    Args:
        premise_name:

    Returns:

    """
    if any(
        [premise_name.endswith(f"_{i}") for i in range(40)]
    ):  # if the premise is of the form assms_1, which in Isabelle is actually assms(1)
        name_split = premise_name.split("_")
        prefix = "_".join(name_split[:-1])
        suffix = "(" + name_split[-1] + ")"
        possible_names = [prefix + suffix, premise_name]
    else:
        possible_names = [premise_name]
    return possible_names