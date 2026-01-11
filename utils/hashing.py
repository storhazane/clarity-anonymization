"""Hashing utilities for anonymization."""
import hashlib
import secrets


def generate_salt():
    """Generate 256-bit salt."""
    return secrets.token_hex(32)


def salted_hash(value, salt):
    """
    Create a salted SHA-256 hash of a value.
    
    Args:
        value: The value to hash
        salt: The salt to use
        
    Returns:
        str: An 8-character uppercase hex hash
    """
    salted_value = f"{salt}{value}{salt}"
    hash_object = hashlib.sha256(salted_value.encode())
    return hash_object.hexdigest()[:8].upper()