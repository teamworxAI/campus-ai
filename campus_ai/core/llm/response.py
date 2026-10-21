from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None
