#!/usr/bin/env bash
set -euo pipefail

: "${DB_HOST:?Set DB_HOST}"
: "${DB_SECRET_ARN:?Set DB_SECRET_ARN}"
: "${S3_BUCKET_NAME:?Set S3_BUCKET_NAME}"

dnf install -y python3.11 python3.11-pip nginx unzip
id ec2-user >/dev/null
install -d -m 0755 -o ec2-user -g ec2-user /opt/student-app
cp -r app.py bootstrap_db.py requirements.txt templates static /opt/student-app/
chown -R ec2-user:ec2-user /opt/student-app
sudo -u ec2-user python3.11 -m venv --clear /opt/student-app/.venv
sudo -u ec2-user /opt/student-app/.venv/bin/python -m pip install --no-cache-dir -r /opt/student-app/requirements.txt

printf 'DB_HOST=%s\nDB_SECRET_ARN=%s\nDB_NAME=studentdb\nS3_BUCKET_NAME=%s\nAWS_DEFAULT_REGION=ap-south-1\nMAX_UPLOAD_MB=5\n' \
  "$DB_HOST" "$DB_SECRET_ARN" "$S3_BUCKET_NAME" > /etc/student-app.env
chmod 0600 /etc/student-app.env

install -m 0644 scripts/flaskapp.service /etc/systemd/system/flaskapp.service
install -m 0644 scripts/student-app.nginx.conf /etc/nginx/nginx.conf
nginx -t
systemctl daemon-reload
systemctl enable --now flaskapp
systemctl enable --now nginx
systemctl restart flaskapp nginx
for attempt in {1..10}; do
  if curl --fail --silent --show-error http://127.0.0.1/ >/dev/null; then
    exit 0
  fi
  sleep 3
done
echo 'Application did not become healthy after 30 seconds.' >&2
exit 1
