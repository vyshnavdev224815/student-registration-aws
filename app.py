import os
import json
import uuid
from functools import lru_cache
from pathlib import Path

import boto3
import pymysql
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "5")) * 1024 * 1024


def required_setting(name: str) -> str:
    """Return a required environment value without embedding secrets in code."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_db_connection():
    credentials = database_credentials()
    return pymysql.connect(
        host=required_setting("DB_HOST"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=credentials["username"],
        password=credentials["password"],
        database=os.environ.get("DB_NAME", "studentdb"),
        charset="utf8mb4",
        connect_timeout=10,
    )


@lru_cache(maxsize=1)
def database_credentials() -> dict[str, str]:
    """Use the RDS-managed secret on EC2, or environment values for local tests."""
    secret_arn = os.environ.get("DB_SECRET_ARN")
    if secret_arn:
        response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        return {"username": secret["username"], "password": secret["password"]}
    return {"username": required_setting("DB_USER"), "password": required_setting("DB_PASSWORD")}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.get("/")
def home():
    return render_template("index.html")


@app.post("/register")
def register():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    course = request.form.get("course", "").strip()
    photo = request.files.get("photo")

    if not all((name, email, course)):
        return render_template("error.html", message="Please complete every required field."), 400

    if not photo or not photo.filename:
        return render_template("error.html", message="Please choose a profile photo to upload."), 400

    if not allowed_file(photo.filename):
        return render_template(
            "error.html", message="Use a JPG, PNG, or WEBP image no larger than 5 MB."
        ), 400

    original_name = secure_filename(photo.filename)
    extension = Path(original_name).suffix.lower()
    object_key = f"student-photos/{uuid.uuid4().hex}{extension}"
    bucket_name = ""
    s3_client = None

    try:
        bucket_name = required_setting("S3_BUCKET_NAME")
        s3_client = boto3.client("s3")  # Uses the attached EC2 IAM role in AWS.
        s3_client.upload_fileobj(
            photo,
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": photo.mimetype or "application/octet-stream"},
        )
        preview_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=300,
        )

        # This stores an S3 locator, not a public object URL. The bucket stays private.
        photo_url = f"s3://{bucket_name}/{object_key}"
        with get_db_connection() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO students (name, email, course, photo_url)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (name, email, course, photo_url),
                )
            db.commit()
    except (BotoCoreError, ClientError, pymysql.MySQLError, RuntimeError):
        # Avoid orphaned uploads when the database insert did not complete.
        if s3_client and bucket_name:
            try:
                s3_client.delete_object(Bucket=bucket_name, Key=object_key)
            except (BotoCoreError, ClientError):
                pass
        app.logger.exception("Student registration failed")
        return render_template(
            "error.html", message="We could not save the registration. Please try again shortly."
        ), 500

    return render_template("success.html", name=name, course=course, photo_url=preview_url)


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_error):
    return render_template("error.html", message="The photo must be 5 MB or smaller."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
