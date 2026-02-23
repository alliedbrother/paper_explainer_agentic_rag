"""Calculator tool for mathematical expressions."""

import math
import operator
from typing import Union

from langchain_core.tools import tool


SAFE_OPERATORS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "**": operator.pow,
    "%": operator.mod,
}

SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
}


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely.

    Supports basic arithmetic (+, -, *, /, **, %) and common math functions
    (sqrt, log, sin, cos, tan, abs, round, min, max, sum).

    Args:
        expression: Mathematical expression to evaluate (e.g., "2 + 2", "sqrt(16)", "sin(pi/2)")

    Returns:
        Result of the calculation or error message
    """
    try:
        # Create safe evaluation environment
        safe_dict = {"__builtins__": {}}
        safe_dict.update(SAFE_FUNCTIONS)

        # Evaluate expression
        result = eval(expression, safe_dict)

        # Format result
        if isinstance(result, float):
            if result.is_integer():
                return str(int(result))
            return f"{result:.6g}"
        return str(result)

    except ZeroDivisionError:
        return "Error: Division by zero"
    except ValueError as e:
        return f"Error: Invalid math operation - {str(e)}"
    except SyntaxError:
        return "Error: Invalid expression syntax"
    except Exception as e:
        return f"Error: {str(e)}"
