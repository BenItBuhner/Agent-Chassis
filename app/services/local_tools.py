from collections.abc import Callable


class LocalToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}

    def register(self, func: Callable):
        """
        Decorator to register a function as a tool.
        """
        self._tools[func.__name__] = func
        return func

    def get_tools(self):
        return self._tools


local_registry = LocalToolRegistry()


# Example local tool
@local_registry.register
def get_server_time():
    """Returns the current server time."""
    from datetime import datetime

    return datetime.now().isoformat()


@local_registry.register
def calculate(operation: str, a: float, b: float) -> str:
    """
    Performs basic arithmetic operations.

    Args:
        operation: One of 'add', 'subtract', 'multiply', 'divide'
        a: First number
        b: Second number
    """
    if operation == "add":
        return str(a + b)
    elif operation == "subtract":
        return str(a - b)
    elif operation == "multiply":
        return str(a * b)
    elif operation == "divide":
        if b == 0:
            return "Error: Division by zero"
        return str(a / b)
    else:
        return f"Error: Unknown operation '{operation}'"
