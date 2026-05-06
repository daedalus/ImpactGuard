# Breaking: removed parameter b
def add(a: int) -> int:
    return a + 1

def greet(name: str) -> None:
    print(f"Hello, {name}!")

if __name__ == "__main__":
    result = add(5)
    greet("World")
