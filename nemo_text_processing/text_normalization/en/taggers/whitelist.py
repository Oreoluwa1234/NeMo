# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
# Copyright 2015 and onwards Google, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from nemo_text_processing.text_normalization.en.graph_utils import NEMO_NOT_SPACE, GraphFst, convert_space
from nemo_text_processing.text_normalization.en.utils import get_abs_path, load_labels

try:
    import pynini
    from pynini.lib import pynutil

    PYNINI_AVAILABLE = True
except (ModuleNotFoundError, ImportError):
    PYNINI_AVAILABLE = False


class WhiteListFst(GraphFst):
    """
    Finite state transducer for classifying whitelist, e.g.
        misses -> tokens { name: "mrs" }
        for non-deterministic case: "Dr. Abc" ->
            tokens { name: "drive" } tokens { name: "Abc" }
            tokens { name: "doctor" } tokens { name: "Abc" }
            tokens { name: "Dr." } tokens { name: "Abc" }
    This class has highest priority among all classifier grammars. Whitelisted tokens are defined and loaded from "data/whitelist.tsv".

    Args:
        input_case: accepting either "lower_cased" or "cased" input.
        deterministic: if True will provide a single transduction option,
            for False multiple options (used for audio-based normalization)
        input_file: path to a file with whitelist replacements
    """

    def __init__(self, input_case: str, deterministic: bool = True, input_file: str = None):
        super().__init__(name="whitelist", kind="classify", deterministic=deterministic)

        def _get_whitelist_graph(input_case, file):
            whitelist = load_labels(file)
            if input_case == "lower_cased":
                whitelist = [(x.lower(), y) for x, y in whitelist]
            else:
                whitelist = [(x, y) for x, y in whitelist]
            graph = pynini.string_map(whitelist)
            return graph

        graph = _get_whitelist_graph(input_case, get_abs_path("data/whitelist.tsv"))
        if not deterministic:
            graph |= _get_whitelist_graph(input_case, get_abs_path("data/whitelist_alternatives.tsv"))

            # convert to states only if comma is present before the abbreviation to avoid converting all caps words,
            # e.g. "IN", "OH", "OK"
            # TODO or only exclude above?
            states = load_labels(get_abs_path("data/address/states.tsv"))
            additional_options = []
            for x, y in states:
                if input_case == "lower_cased":
                    x = x.lower()
                additional_options.append((x, f"{y[0]}. {y[1:]}"))
                additional_options.append((x, f"{y[0]}.{y[1:]}"))
                additional_options.append((x, f"{y[0].upper()}{y[1:].lower()}"))
                additional_options.append((x, f"{y[0].upper()}.{y[1:].lower()}"))
                additional_options.append((x, f"{y[0].upper()}. {y[1:].lower()}"))
            states.extend(additional_options)
            state_graph = pynini.string_map(states)
            graph |= (
                pynini.closure(NEMO_NOT_SPACE, 1) + pynini.union(", ", ",") + pynini.invert(state_graph).optimize()
            )

        if input_file:
            whitelist_provided = _get_whitelist_graph(input_case, input_file)
            if not deterministic:
                graph |= whitelist_provided
            else:
                graph = whitelist_provided

        self.graph = (convert_space(graph)).optimize()
        self.fst = (pynutil.insert("name: \"") + self.graph + pynutil.insert("\"")).optimize()
