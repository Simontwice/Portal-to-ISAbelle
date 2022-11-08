from __future__ import print_function

import os
import grpc

from func_timeout import func_set_timeout, FunctionTimedOut
from typing import List

from pisa.src.main.python import server_pb2, server_pb2_grpc
from pathlib import Path
from pisa.src.main.python.misc_utils import (
    trim_string_optional,
    process_raw_global_facts,
    process_raw_facts,
)

MAX_MESSAGE_LENGTH = 100485760


class EmptyInitialStateException(Exception):
    pass


class InitFailedException(Exception):
    pass


class EnvInitFailedException(Exception):
    pass


class ProceedToLineFailedException(Exception):
    pass


class StepToTopLevelStateException(Exception):
    pass


class AvailableFactsExtractionError(Exception):
    pass


class AvailableFactsTimeout(Exception):
    pass


class _InactiveRpcError(Exception):
    pass


def create_stub(port=9000):
    channel = grpc.insecure_channel(
        "localhost:{}".format(port),
        options=[
            ("grpc.max_send_message_length", MAX_MESSAGE_LENGTH),
            ("grpc.max_receive_message_length", MAX_MESSAGE_LENGTH),
        ],
    )
    return server_pb2_grpc.ServerStub(channel)


class IsaFlexEnv:
    def __init__(
        self,
        port=9000,
        isa_path="/Applications/Isabelle2020.app/Isabelle",
        starter_string="theory Test imports Complex_Main begin",
        working_directory="/Users/qj213/Projects/afp-2021-02-11/thys/Functional-Automata",
    ):
        self.port = port
        self.isa_path = isa_path
        self.starter_string = starter_string
        self.working_directory = working_directory

        self.stub = None
        self.obs_string = None
        self.successful_starting = False
        self.reset()

    def observation(self):
        return self.obs_string

    def is_finished(self, name_of_tls):
        returned_string = self.stub.IsabelleCommand(
            server_pb2.IsaCommand(command=f"<is finished> {name_of_tls}")
        ).state.strip()
        if returned_string.startswith("t"):
            return True
        else:
            return False

    @staticmethod
    def reward(done):
        return 1.0 if done else 0.0

    def reset(self):
        self.stub = create_stub(port=self.port)
        try:
            print(
                self.stub.InitialiseIsabelle(
                    server_pb2.IsaPath(path=self.isa_path)
                ).message
            )
            print(
                self.stub.IsabelleWorkingDirectory(
                    server_pb2.IsaPath(path=self.working_directory)
                ).message
            )
            print(
                self.stub.IsabelleContext(
                    server_pb2.IsaContext(context=self.starter_string)
                ).message
            )
            self.successful_starting = True
            print("Successfully initialised an Isabelle process")
        except Exception as e:
            print(
                "Failure at initialising Isabelle process. "
                "Make sure the path your provide is where the Isabelle executable is."
            )
            print(e)
        return self.obs_string

    @func_set_timeout(1800, allowOverride=True)
    def step_to_top_level_state(self, action, tls_name, new_name):
        obs_string = "Step error"
        done = False
        try:
            obs_string = self.stub.IsabelleCommand(
                server_pb2.IsaCommand(
                    command=f"<apply to top level state> {tls_name} <apply to top level state> {action} <apply to top level state> {new_name}"
                )
            ).state
        except Exception as e:
            print("***Something went wrong***")
            print(e)

        done = self.is_finished(new_name)
        return obs_string, self.reward(done), done, {}

    def proceed_after(self, line_string):
        return self.post(f"<proceed after> {line_string}", forceTimeout=10000)

    def clone_to_new_name(self, new_name):
        return self.post(f"<clone> default <clone> {new_name}", forceTimeout=10)

    def get_proof_level(self,tls_name="default"):
        return self.post(f"<get_proof_level> {tls_name}")

    @func_set_timeout(1800, allowOverride=True)
    def post(self, action):
        return self.stub.IsabelleCommand(server_pb2.IsaCommand(command=action)).state

    def proceed_to_line(self, line_stirng, before_after):
        assert before_after in ["before", "after"]
        try:
            command = f"<proceed {before_after}> {line_stirng}"
            print(command)
            message = self.stub.IsabelleCommand(
                server_pb2.IsaCommand(command=command)
            ).state
            print(message)
            return message
        except Exception as e:
            print(f"Failure to proceed {before_after} line")
            print(e)
            raise ProceedToLineFailedException

    def local_facts(self, tls_name="default"):
        try:
            return self.post(f"<local facts and defs> {tls_name}")
        except:
            return "failed"

    def global_facts(self, tls_name="default"):
        try:
            facts = self.post(f"<global facts and defs> {tls_name}")
            return facts
        except FunctionTimedOut:
            raise AvailableFactsTimeout

    def dataset_extraction_global_facts(self, isabelle_state):
        """
        for dataset extraction purposes
        :param isabelle_state:
        :return:
        """
        _global = self.global_facts(tls_name=isabelle_state)
        unpacked_premises = process_raw_facts(_global)
        unpacked_premises = dict(
            filter(lambda item: not item[0].startswith("??"), unpacked_premises.items())
        )
        translated_premises = {}
        for premise_name, premise_statement in unpacked_premises.items():
            translated_name, non_translated_name = self.translate_premise_names(isabelle_state, premise_name)
            if len(translated_name):
                translated_name = translated_name[0]
            else:
                translated_name = non_translated_name[0]
            translated_premises[translated_name] = premise_statement
        return translated_premises

    def dataset_extraction_local_facts(self, isabelle_state):
        """
        for dataset extraction purposes
        :param isabelle_state:
        :return:
        """
        _local = self.local_facts(tls_name=isabelle_state)
        unpacked_premises = process_raw_facts(_local)
        unpacked_premises = dict(
            filter(lambda item: not item[0].startswith("??"), unpacked_premises.items())
        )
        translated_premises = {}
        for premise_name, premise_statement in unpacked_premises.items():
            translated_name, non_translated_name = self.translate_premise_names(isabelle_state, premise_name)
            if len(translated_name):
                translated_name = translated_name[0]
                translated_name = translated_name[0]
            else:
                translated_name = non_translated_name[0]
            translated_premises[translated_name] = premise_statement
        return translated_premises

    def all_facts_processed(self, dataset_extraction=False):
        _global = self.global_facts()
        _local = self.local_facts()

        if dataset_extraction:
            processed_global = process_raw_global_facts(_global)
        else:
            processed_global = process_raw_facts(_global)
        processed_local = process_raw_facts(_local)
        processed_global.update(processed_local)
        processed_global = dict(
            filter(lambda item: not item[0].startswith("??"), processed_global.items())
        )

        return processed_global

    def translate_premise_names(self, isabelle_state, premise_names: List[str]):
        """

        Args:
            premise_names: list of premise names, some of them of the form *_{n} for some natural n >= 1

        Returns:
            a corrected list of the names, where each of the names is validated to be visible in the env. Some _{n} are transformed to (n), as appropriate.
            It is possible that both _{n} and (n) are returned for some names, though it should be extremely rare

        """
        successful_steps: List[str] = []
        unsuccessful_premises: List[str] = []

        for premise in premise_names:
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
                next_proof_state, _, done, _ = self.step_to_top_level_state(
                    step,
                    isabelle_state.proof_state_id,
                    -1,
                )

                next_proof_state_clean = trim_string_optional(next_proof_state)
                step_correct = (
                    "Step error: Undefined fact" not in next_proof_state_clean
                )
                if step_correct:
                    successful_steps.append(step)
                    step_successful = True
            if not step_successful:
                unsuccessful_premises.append(premise)

        translated_premises = [step.split()[-1] for step in successful_steps]
        return translated_premises, unsuccessful_premises

    @func_set_timeout(100, allowOverride=True)
    def initialise_toplevel_state_map(self):
        try:
            obs_string = self.stub.IsabelleCommand(
                server_pb2.IsaCommand(command="<initialise>")
            ).state
            print(obs_string)
            return obs_string
        except Exception as e:
            print("**Unsuccessful initialisation**")
            raise InitFailedException

    @func_set_timeout(500, allowOverride=True)
    def extract_theory_steps(self):
        all_steps_str = self.stub.IsabelleCommand(
            server_pb2.IsaCommand(command="PISA extract actions")
        ).state
        list_of_steps = all_steps_str.split("<\\ISA_STEP>")
        list_of_useful_steps = []
        for step in list_of_steps:
            if not step.startswith("(*") and len(step) > 0:
                list_of_useful_steps.append(step)
        return list_of_useful_steps


def initialise_env(
    port,
    isa_path,
    theory_file_path=None,
    working_directory=None,
    test_theorems_only=False,
):
    if working_directory is None:
        actual_working_dir_candidate = str(Path(theory_file_path).parents[0])
        i = 0
        success = False
        # if we are only concerned with universal_test_theorems, then the working_directory path is one that ends with /thys/xyz and the task is much simpler
        if test_theorems_only:
            layers = theory_file_path.split("/")
            while layers[-2] != "thys" and len(layers) > 2:
                layers = layers[:-1]
            try:
                assert layers[-2] == "thys"
                working_directory = os.path.join(*layers)
                if not working_directory.startswith("/"):
                    working_directory = "/" + working_directory.strip()

                env = IsaFlexEnv(
                    port=port,
                    isa_path=isa_path,
                    starter_string=theory_file_path,
                    working_directory=working_directory,
                )
                success = True
            except AssertionError:
                raise EnvInitFailedException

        # in case of dataset extraction etc, we have to be more generic
        else:
            while not success and i < 10:
                try:
                    env = IsaFlexEnv(
                        port=port,
                        isa_path=isa_path,
                        starter_string=theory_file_path,
                        working_directory=actual_working_dir_candidate,
                    )
                    success = True
                except:
                    actual_working_dir_candidate = str(
                        Path(actual_working_dir_candidate).parents[0]
                    )
                    i += 1
        if success:
            print(
                f"Automatically detected working directory: {actual_working_dir_candidate}"
            )
        else:
            print(
                f"Did not manage to detect working directory: {actual_working_dir_candidate}"
            )
            raise EnvInitFailedException
    return env
