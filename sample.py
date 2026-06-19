# Program to determine voting eligibility based on age

def check_voting_eligibility(age):
    """Check if a person is eligible to vote based on their age."""
    voting_age = 18
    if age >= voting_age:
        return f"You are {age} years old and eligible to vote."
    else:
        return f"You are {age} years old and not eligible to vote. You need to be at least {voting_age} years old."

if __name__ == "__main__":
    try:
        user_age = int(input("Enter your age: "))
        print(check_voting_eligibility(user_age))
    except ValueError:
        print("Please enter a valid integer for age.")
