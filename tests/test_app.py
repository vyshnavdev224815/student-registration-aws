import io
import os
import unittest
from unittest.mock import MagicMock, patch

from app import app, database_credentials


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        database_credentials.cache_clear()

    def tearDown(self):
        database_credentials.cache_clear()

    def test_form_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Registration form", response.data)

    def test_photo_is_required(self):
        response = self.client.post(
            "/register",
            data={"name": "Test Student", "email": "student@example.com", "course": "Cloud Computing"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("app.get_db_connection")
    @patch("app.boto3.client")
    def test_registration_uploads_and_inserts(self, boto_client, get_connection):
        database = MagicMock()
        get_connection.return_value.__enter__.return_value = database
        database.cursor.return_value.__enter__.return_value = MagicMock()
        boto_client.return_value.generate_presigned_url.return_value = "https://example.com/photo"
        with patch.dict(os.environ, {"S3_BUCKET_NAME": "test-student-photos"}):
            response = self.client.post(
                "/register",
                data={
                    "name": "Test Student",
                    "email": "student@example.com",
                    "course": "Cloud Computing",
                    "photo": (io.BytesIO(b"test-image"), "portrait.jpg", "image/jpeg"),
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome, Test Student", response.data)
        boto_client.return_value.upload_fileobj.assert_called_once()
        boto_client.return_value.generate_presigned_url.assert_called_once()
        database.commit.assert_called_once()

    @patch("app.boto3.client")
    def test_managed_secret_is_used_when_set(self, boto_client):
        boto_client.return_value.get_secret_value.return_value = {
            "SecretString": '{"username":"studentowner","password":"example"}'
        }
        with patch.dict(os.environ, {"DB_SECRET_ARN": "arn:aws:secretsmanager:example"}):
            self.assertEqual(database_credentials()["username"], "studentowner")
        boto_client.return_value.get_secret_value.assert_called_once()


if __name__ == "__main__":
    unittest.main()
