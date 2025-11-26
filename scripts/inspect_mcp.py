import inspect

import mcp.types

for name, _ in inspect.getmembers(mcp.types, predicate=inspect.isclass):
    print(name)
