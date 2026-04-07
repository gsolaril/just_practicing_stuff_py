__all__ = ["__version__", "hello", "meaning_of_packaging"]
__version__ = "0.1.0"

def hello(name: str = "world") -> str:
    return f"hello, {name}"

def meaning_of_packaging() -> str:
    return "Package once, install reproducibly."
