"""Simple greeting module."""


def greet(name: str) -> str:
    """
    Return a friendly greeting message.
    
    Args:
        name: The name of the person to greet.
        
    Returns:
        A greeting string.
        
    Raises:
        ValueError: If name is empty or contains only whitespace.
    """
    if not name or not name.strip():
        raise ValueError("Name cannot be empty or contain only whitespace")
    
    return f"Hello, {name.strip()}!"


def greet_formal(name: str, title: str = "Mr./Ms.") -> str:
    """
    Return a formal greeting message.
    
    Args:
        name: The name of the person to greet.
        title: The title to use (default: "Mr./Ms.").
        
    Returns:
        A formal greeting string.
        
    Raises:
        ValueError: If name is empty or contains only whitespace.
    """
    if not name or not name.strip():
        raise ValueError("Name cannot be empty or contain only whitespace")
    
    return f"Good day, {title} {name.strip()}!"


if __name__ == "__main__":
    # Example usage
    print(greet("World"))
    print(greet_formal("Smith", "Dr."))
