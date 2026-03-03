# Rekognition Bridge – AWS Quickstart

This guide walks you through setting up the AWS infrastructure required by the Rekognition Bridge add-on from scratch.

---

## Quick Checklist

- [ ] AWS account created
- [ ] AWS CLI installed and configured (`aws configure`)
- [ ] S3 bucket created in your target region
- [ ] Rekognition face collection created
- [ ] IAM user / role created with least-privilege policy
- [ ] AWS credentials (`Access Key ID` + `Secret Access Key`) noted
- [ ] At least one face image indexed into the collection
- [ ] Add-on installed in Home Assistant and configured

---

## 1. Prerequisites

- An **AWS account** ([sign up](https://aws.amazon.com/free/))
- **AWS CLI v2** installed ([install guide](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html))
- A target **AWS region** – replace `REGION` throughout this guide (e.g. `ap-southeast-2`, `us-east-1`)

Configure the CLI with an admin user first (you will tighten permissions in step 4):

```bash
aws configure
# AWS Access Key ID:     <your admin key>
# AWS Secret Access Key: <your admin secret>
# Default region name:   REGION
# Default output format: json
```

---

## 2. Create an S3 Bucket

```bash
BUCKET="your-ha-rekognition-bucket"
REGION="ap-southeast-2"

# Create the bucket (use --create-bucket-configuration only outside us-east-1)
aws s3api create-bucket \
  --bucket "$BUCKET" \
  --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"

# Block all public access
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

> **Note:** Bucket names must be globally unique. Pick a name that identifies your deployment (e.g. `ha-rekognition-yourname-2024`).

---

## 3. Create a Rekognition Face Collection

```bash
COLLECTION="ha_known_people"
REGION="ap-southeast-2"

aws rekognition create-collection \
  --collection-id "$COLLECTION" \
  --region "$REGION"
```

A successful response looks like:

```json
{
    "StatusCode": 200,
    "CollectionArn": "aws:rekognition:ap-southeast-2:123456789012:collection/ha_known_people",
    "FaceModelVersion": "7.0"
}
```

---

## 4. Create an IAM User with Least-Privilege Policy

### 4a. Create the policy document

Save the following JSON to a file called `rekognition-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3SnapshotAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::your-ha-rekognition-bucket/snapshots/*"
    },
    {
      "Sid": "RekognitionFaceOps",
      "Effect": "Allow",
      "Action": [
        "rekognition:DetectFaces",
        "rekognition:SearchFacesByImage",
        "rekognition:IndexFaces",
        "rekognition:ListFaces",
        "rekognition:DeleteFaces"
      ],
      "Resource": "arn:aws:rekognition:REGION:ACCOUNT_ID:collection/ha_known_people"
    }
  ]
}
```

Replace `your-ha-rekognition-bucket`, `REGION`, and `ACCOUNT_ID` with your actual values.

### 4b. Create the IAM policy and user

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="ap-southeast-2"
BUCKET="your-ha-rekognition-bucket"
COLLECTION="ha_known_people"

# Substitute placeholders in the policy file (the .bak suffix keeps macOS and Linux sed compatible)
sed -i.bak "s/your-ha-rekognition-bucket/$BUCKET/g; s/REGION/$REGION/g; s/ACCOUNT_ID/$ACCOUNT_ID/g" rekognition-policy.json && rm -f rekognition-policy.json.bak

# Create the managed policy
POLICY_ARN=$(aws iam create-policy \
  --policy-name HASSRekognitionPolicy \
  --policy-document file://rekognition-policy.json \
  --query 'Policy.Arn' --output text)

echo "Policy ARN: $POLICY_ARN"

# Create the IAM user
aws iam create-user --user-name hass-rekognition

# Attach the policy
aws iam attach-user-policy \
  --user-name hass-rekognition \
  --policy-arn "$POLICY_ARN"

# Create access keys (save the output – you will not see the secret again!)
aws iam create-access-key --user-name hass-rekognition
```

Store the `AccessKeyId` and `SecretAccessKey` from the last command – you will paste them into the add-on configuration.

---

## 5. Index Known Faces into the Collection

For each person you want recognised, provide a clear, front-facing portrait photo (JPEG or PNG).

```bash
COLLECTION="ha_known_people"
REGION="ap-southeast-2"
BUCKET="your-ha-rekognition-bucket"

# Upload the reference photo to S3
aws s3 cp john.jpg s3://$BUCKET/faces/john.jpg

# Index the face – ExternalImageId becomes the "name" returned on a match
aws rekognition index-faces \
  --collection-id "$COLLECTION" \
  --image '{"S3Object":{"Bucket":"'"$BUCKET"'","Name":"faces/john.jpg"}}' \
  --external-image-id "john" \
  --region "$REGION"
```

Repeat for each person. The `ExternalImageId` (e.g. `john`) is what the add-on returns as the `name` field in match results.

To list all indexed faces:

```bash
aws rekognition list-faces --collection-id "$COLLECTION" --region "$REGION"
```

---

## 6. Configure the Add-on in Home Assistant

Once the AWS infrastructure is ready, fill in the add-on **Configuration** tab:

| Field | Value |
|---|---|
| `aws_access_key_id` | From step 4b (`AccessKeyId`) |
| `aws_secret_access_key` | From step 4b (`SecretAccessKey`) |
| `aws_region` | Your region (e.g. `ap-southeast-2`) |
| `rekognition_collection` | Collection ID from step 3 (e.g. `ha_known_people`) |
| `s3_bucket` | Bucket name from step 2 |
| `s3_prefix` | `snapshots/` (or a custom prefix) |
| `default_threshold` | `95` (lower to be more permissive, raise to be stricter) |
| `delete_after_match` | `true` – removes the snapshot from S3 after processing |
| `ha_url` | `http://172.30.32.1:8123` (internal HA supervisor URL) |
| `ha_token` | Long-lived access token from your HA profile |
| `helper_person_name` | `input_text.rekognition_person_name` |
| `helper_person_similarity` | `input_number.rekognition_person_similarity` |
| `helper_person_status` | `input_text.rekognition_person_status` |

See the main [README](README.md) for the full configuration reference and API documentation.

---

## 7. Verify the Setup

After starting the add-on, test it with a `curl` request from within your HA environment (or via the HA terminal add-on):

```bash
curl -s -X POST http://localhost:8080/match \
  -H "Content-Type: application/json" \
  -d '{"snapshot_path": "/media/snapshots/test.jpg", "threshold": 80}'
```

A successful match returns:

```json
{
  "status": "matched",
  "matched": true,
  "name": "john",
  "similarity": 98.72,
  "faces_detected": 1,
  "threshold": 80
}
```

Check `GET http://localhost:8080/health` to confirm the service is running.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `AccessDenied` errors in logs | IAM policy missing an action or wrong ARN | Re-check the policy ARNs match your bucket/collection/region |
| `no_face` status | Image too small or face not visible | Use a higher-resolution, well-lit front-facing photo |
| `no_match` status | Threshold too high, or face not indexed | Lower `default_threshold` or re-index the face |
| Add-on fails to start | Invalid AWS credentials | Confirm `aws_access_key_id` / `aws_secret_access_key` are correct |
| High false-positive rate | Threshold too low | Raise `default_threshold` (95–99 recommended) |
