import random, string

haystack = string.ascii_letters + string.digits + string.punctuation
print(''.join([random.SystemRandom().choice(haystack.replace('/','').replace('\'', '').replace('\"','')) for _ in range(50)]))