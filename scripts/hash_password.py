"""Print a bcrypt hash for a password, to put in ADMIN_PASSWORD_HASH.

Usage: python scripts/hash_password.py 'my-new-password'
"""

import sys

import bcrypt

if len(sys.argv) != 2:
    sys.exit("usage: python scripts/hash_password.py <password>")
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())
