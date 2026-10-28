"""LLM router: the single entry point product code uses to call a model.

Every call goes to a local open-weight model on Ollama (prime directive 2),
declares the data class of its messages (class R is refused before any model
call, card P1b) and writes a trace record (card P2).
"""

from campus_ai.core import data_classes, tracing

from . import backends, config
from .response import LLMResponse


def generate(messages, task, data_class, system=None) -> LLMResponse:
    """Run `messages` (text and base64 image blocks) on the local model for `task`.

    `data_class` is the class (P, I, S or R) of the messages and system prompt.
    """
    if task not in config.TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {config.TASKS}")
    host = config.ollama_host()
    with tracing.span("llm", task=task, data_class=data_class, host=host) as trace:
        data_classes.check(data_class)
        trace["model"] = config.model(task)
        response = backends.ollama(messages, trace["model"], config.MAX_TOKENS[task], host, system,
                                   think=config.THINK[task])
        trace.update(model=response.model, input_tokens=response.input_tokens, output_tokens=response.output_tokens)
    return response
