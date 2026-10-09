# Secure Student Registration on AWS

This Flask application registers a student, uploads the submitted photo to Amazon S3, and writes the registration record to MySQL on Amazon RDS. The deployment template is in `infrastructure/student-app.yaml` and uses the Mumbai region (`ap-south-1`).

## Security design

- Configuration comes from environment variables; credentials and bucket names are never hardcoded.
- `boto3` uses the EC2 instance role. Do not create access keys or put them in a `.env` file.
- Photos are stored in a private bucket. The database retains an `s3://` object locator; the success page shows a five-minute pre-signed preview URL.
- The app only accepts JPG, PNG, and WEBP uploads up to 5 MB and creates a random object key for each file.
- If the database write fails after a photo upload, the app attempts to remove that orphaned object.
- On EC2, the database password is held in the RDS-managed Secrets Manager secret, and the instance role retrieves it. No password is passed in a CloudFormation parameter or committed to this repository.

## Local configuration

Copy `.env.example` into a private environment file or export the variables in your shell. The application does not load `.env` files automatically, which prevents accidental use of secrets in production.

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Architecture

```text
Internet --HTTP:80--> EC2 (public 10.0.1.0/24, Nginx -> Gunicorn/Flask)
                         |--MySQL:3306--> RDS MySQL (private 10.0.2.0/24,
                         |                            subnet group also 10.0.3.0/24)
                         |--HTTPS, IAM role--> private S3 photo bucket
                         `--HTTPS, IAM role--> RDS-managed database secret
```

The RDS subnets have no internet-gateway or NAT route. The database security group accepts MySQL only from the EC2 security group. The S3 bucket blocks all public access; photo objects are displayed only through five-minute pre-signed URLs. The app stores an `s3://` locator. Nginx serves HTTP for the assignment; a trusted HTTPS domain would be the next improvement before collecting real student data.

## Deployment

The CloudFormation template creates a dedicated VPC, public/private subnets, route tables, security groups, S3 bucket, RDS MySQL 8.4, an EC2 role, and an Amazon Linux 2023 `t3.micro` instance. The EC2 install script uses Nginx, Gunicorn, and systemd. `bootstrap_db.py` creates the assignment's table from inside the VPC.

The template deliberately excludes a NAT gateway and load balancer to conserve Free-plan credits. The S3 bucket and RDS database are retained on stack deletion to prevent accidental loss; explicitly remove those two resources after saving any required evidence if you want to stop all related charges. The database's RDS-managed secret may also incur a small charge covered by credits while the Free plan is active. Do not assume this design remains free after credits or the Free plan expire.

Run local checks with `python -m unittest discover -s tests -v`. Deployment requires access to AWS account resources and a key pair that you control. No credentials or `.pem` file should be committed.
