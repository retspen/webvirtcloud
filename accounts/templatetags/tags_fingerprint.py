from django import template
import base64
import hashlib

register = template.Library()


@register.simple_tag
def ssh_to_fingerprint(line):
    try:
        key = base64.b64decode(line.strip().split()[1].encode('ascii'))
        fp_plain = hashlib.md5(key).hexdigest()
        return ':'.join(a + b for a, b in zip(fp_plain[::2], fp_plain[1::2]))
    except Exception:
        return 'Invalid key'
