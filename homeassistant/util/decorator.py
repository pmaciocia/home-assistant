"""Decorator utility functions."""


def register_decorator_factory(registry):
    """Create a decorator that registers functions in a registry."""
    def name_decorator(name):
        """Create a decorator to register function with a specific name."""
        def decorator(func):
            """Register decorated function."""
            registry[name] = func
            return func

        return decorator

    return name_decorator
