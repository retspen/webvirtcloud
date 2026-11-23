# REST API

The REST API (Django REST Framework, documented with `drf-spectacular`) takes the login session or an API token. After logging in:

* **Swagger UI:** `http://<server>/swagger/`
* **ReDoc UI:** `http://<server>/redoc/`
* **OpenAPI 3.0 schema:** `http://<server>/api/schema/` (JSON or YAML)

## API tokens

For scripts and tools: **Profile → API Tokens**. A token acts as its user and is shown once. Setting a user's password (as an administrator) deletes that user's tokens. Send it as a header:

```bash
curl -H "Authorization: Token wvc_..." https://<server>/api/v1/instances/
```

## Requests

- **Tags:** the VM and compute lists (also a compute's VMs) take `?tag=<name>`.
- **Jobs:** VM create, migrate and delete answer 202 with the job and need a `submission_key`: a new one for each operation, the same one to retry it (a delete retried after its VM is gone gets 404). `/api/v1/operations/` follows the jobs.
- **Errors:** a field the request got wrong answers with the fields. Any other error is `{"detail": ...}` with a status that says what it is: 404 for a VM, pool or volume read or deleted that the host does not have, 409 for a volume in use, a template started or a stopped pool, 503 for a host that cannot be reached. An unknown API URL answers JSON.
