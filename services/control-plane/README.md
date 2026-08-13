# Control Plane

Java 21 Spring Boot service for identity, projects, node catalog, drafts, and publish.

## Run locally

```powershell
cd services/control-plane
$env:AIW_CONTRACTS_ROOT = (Resolve-Path ..\..\contracts).Path
./mvnw spring-boot:run
```

Or with Compose (from repo root):

```powershell
docker compose up --build postgres control-plane
```

API: `http://localhost:8080/api/v1`

Postman: import `postman/control-plane-f1-f5.postman_collection.json` and `postman/control-plane.local.postman_environment.json`.
