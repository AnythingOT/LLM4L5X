"""Plain English -> LogicSpec with a local model through Ollama.

The model only writes LogicSpec. Everything after that is checked code:
parse, compile, validate. When a check fails, the exact error goes back to
the model for another try. Nothing the model writes reaches an L5X unchecked.

    gen = Generator(OllamaClient(model="phi4-mini"))
    result = gen.generate("start the pump with start, stop with stop", known_tags={...})

Split by function (same public names as the old single module):
    clients   - Ollama / OpenAI-compatible HTTP clients, LLMError, BACKENDS, make_client
    prompt    - SYSTEM_PROMPT, examples, which examples and tags a request is shown
    names     - tag names in requests and specs (extract_spec, plain_names, snap_tags...)
    checks    - output checks that send the model back (output_problems, near_miss_warnings)
    generator - Generator, Attempt, Result: the retry loop tying it all together
"""

from .checks import near_miss_warnings, output_problems
from .clients import (BACKENDS, MAX_TOKENS, LLMError, OllamaClient, OpenAICompatClient, check_url, is_local_url,
                      make_client)
from .generator import RETRY_CODES, Attempt, Generator, Result
from .names import extract_spec, plain_names, request_identifiers, snap_tags, spec_tags
from .prompt import EXAMPLES_FILE, SYSTEM_PROMPT, load_examples, pick_examples, pick_tags

__all__ = ["BACKENDS", "EXAMPLES_FILE", "MAX_TOKENS", "RETRY_CODES", "SYSTEM_PROMPT", "Attempt", "Generator",
           "LLMError", "OllamaClient", "OpenAICompatClient", "Result", "check_url", "extract_spec", "is_local_url", "load_examples",
           "make_client", "near_miss_warnings", "output_problems", "pick_examples", "pick_tags", "plain_names",
           "request_identifiers", "snap_tags", "spec_tags"]
