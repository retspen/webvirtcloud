# REST API

The REST API (Django REST Framework, documented with `drf-spectacular`) takes the login session or an API token. After logging in:

* **Swagger UI:** `http://<server>/swagger/`
* **ReDoc UI:** `http://<server>/redoc/`
* **OpenAPI 3.0 schema:** `http://<server>/api/schema/` (JSON or YAML)
* **API tokens**, for scripts and tools: **Profile → API Tokens**. A token acts as its user and is shown once; an administrator who sets the user's password deletes them. Send it as a header:

  ```bash
  curl -H "Authorization: Token wvc_..." https://<server>/api/v1/instances/
  ```

  The VM and compute lists (also a compute's VMs) take `?tag=<name>`.
