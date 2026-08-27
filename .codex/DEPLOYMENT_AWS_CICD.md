# AWS / Docker Hub Deployment Notes

Last reviewed: 2026-08-27

## Current Goal

Deploy the Django backend to AWS EC2 without a custom domain for the first pass.

Important caveat:

- `http://<EC2_PUBLIC_IP>/api/docs/` is fine for smoke testing the backend.
- Live Telegram and Meta/WhatsApp webhooks should be treated as blocked until there is a public HTTPS URL. Use a temporary HTTPS tunnel for testing or add a domain plus TLS certificate for production.

Runtime plan:

- GitHub Actions builds the backend Docker image.
- The image is pushed to Docker Hub.
- EC2 pulls the latest image.
- Backend repo lives in `/opt/tattoo-hysteria-backend`.
- AI repo lives separately in `/opt/tattoo-hysteria-ai`.
- `docker-compose.prod.yml` runs backend, Postgres, Redis, and nginx.
- nginx listens on port `80` and proxies to gunicorn on port `8007`.
- Media uploads should use S3 when `USE_S3=True`.
- Backend and AI should join the external Docker network `tattoo_hysteria_net` so the backend can call the AI container privately by service/container name.
- After backend deploy, CI runs `docker image prune -af` to remove unused Docker images while preserving running containers, volumes, and networks.

## Files

- `.github/workflows/pipeline.yml`
- `Dockerfile`
- `docker/start-web.sh`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `nginx/default.conf`
- `nginx/default.ssl.conf.template`
- `.env.example`

## GitHub Configuration

Required repository variables:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_REPOSITORY`, optional, defaults to `tattoo-hysteria-backend`

Required repository secrets:

- `DOCKERHUB_TOKEN`

EC2 deployment is disabled until this variable is set:

- `ENABLE_EC2_DEPLOY=true`

Required EC2 deployment secrets once enabled:

- `EC2_HOST`
- `EC2_USER`
- `EC2_SSH_KEY`
- `EC2_SSH_PORT`, optional

Optional EC2 deployment variable:

- `EC2_APP_DIR`, defaults to `/opt/tattoo-hysteria-backend`

## EC2 Runtime Environment

The EC2 server should have:

- Docker Engine.
- Docker Compose plugin.
- External Docker network: `docker network create tattoo_hysteria_net`.
- This repository checked out in `/opt/tattoo-hysteria-backend`.
- AI repository checked out separately in `/opt/tattoo-hysteria-ai`.
- A production `.env` file in that directory.
- Security group inbound rule for HTTP `80`.
- Security group inbound rule for SSH `22`, restricted to the developer IP where possible.
- HTTPS `443` once a domain/TLS certificate is added.
- Let's Encrypt certificates on the host under `/etc/letsencrypt`.
- Optional ACME webroot directory under `/var/www/certbot`.

Do not commit `.env`.

## Production `.env` Notes

Use production values:

- `DEBUG=False`
- `ALLOWED_HOSTS=<EC2_PUBLIC_IP>`
- `CSRF_TRUSTED_ORIGINS=http://<EC2_PUBLIC_IP>`
- After domain/SSL, use `ALLOWED_HOSTS=<api-domain>` and `CSRF_TRUSTED_ORIGINS=https://<api-domain>`.
- `SERVE_MEDIA=False` when S3 is enabled.
- `USE_S3=True`
- `AWS_STORAGE_BUCKET_NAME=<bucket>`
- `AWS_S3_REGION_NAME=<region>`
- `DOCKER_IMAGE=<dockerhub_username>/<repo>:latest`

The app supports either:

- `DATABASE_URL=postgres://...`
- or `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.

For first-pass EC2 Docker Compose, the bundled Postgres container is acceptable. For production durability, consider AWS RDS later.

## Verification

After deploy:

- Visit `http://<EC2_PUBLIC_IP>/`.
- Visit `http://<EC2_PUBLIC_IP>/api/docs/`.
- Confirm admin loads at `http://<EC2_PUBLIC_IP>/admin/`.
- Use temporary HTTPS tunneling or a real domain/TLS setup before configuring live Telegram or Meta/WhatsApp webhooks.

## SSL Setup Notes

For a GoDaddy-managed subdomain such as `api.example.com`:

1. Add an `A` record pointing `api` to the EC2 Elastic IP.
2. Allow inbound `443` in the EC2 security group.
3. Issue a Let's Encrypt certificate on EC2 with Certbot standalone while the Docker nginx container is stopped.
4. Replace `api.YOUR_DOMAIN.com` in `nginx/default.ssl.conf.template` with the real API domain.
5. Copy the SSL template into `nginx/default.conf` and redeploy.

The production compose mounts `/etc/letsencrypt` read-only into the nginx container and publishes both `80` and `443`.
