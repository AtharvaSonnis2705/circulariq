"""Claude prices, used to report cost per answer in traces and evals."""

# USD per million tokens (input, output), from Anthropic's published prices (2026-10).
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, PRICES["claude-sonnet-5-5"])
    return (input_tokens * price_in + output_tokens * price_out) / 1e6
