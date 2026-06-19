def factorial(n):
    """Calculate the factorial of a non-negative integer n."""
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers.")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result

if __name__ == "__main__":
    # Example usage
    number = 5
    print(f"The factorial of {number} is {factorial(number)}")
