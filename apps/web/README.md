# Web app

React workbench for the AI Workflow platform. Talks only to the Spring control plane at `/api/v1`.

```bash
cd apps/web
npm install
npm run dev
```

Vite proxies `/api` to `http://localhost:8080`. Sign in at `/login`. After login you land on **Projects**.

```bash
npm test
npm run build
```
