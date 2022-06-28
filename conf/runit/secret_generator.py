import secrets

generated_key = secrets.token_urlsafe(50)

print(''.join(generated_key))


### Use for old python versions < 3.6
##import random
##import string
#
##haystack = string.ascii_letters + string.digits + string.punctuation
##print(''.join([random.SystemRandom().choice(haystack.replace('/', '').replace('\'', '').replace('\"', '')) for _ in range(50)]))
