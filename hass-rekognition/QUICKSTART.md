# Rekognition Bridge – AWS Quickstart Guide

This guide walks you through the minimum AWS setup required to run the **Rekognition Bridge** Home Assistant add-on from scratch.

---

## Quick Checklist

- [ ] AWS account with Rekognition and S3 access
- [ ] S3 bucket created in your target region
- [ ] Rekognition face collection created
- [ ] IAM user created with least-privilege policy
- [ ] Access key generated and saved
- [ ] At least one face enrolled in the collection
- [ ] Add-on installed and configured in Home Assistant

---

## Prerequisites

- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) installed and configured (`aws configure`)
- An AWS account with billing enabled
- The region you plan to use – this guide uses **`ap-southeast-2`** (Sydney). Replace it with your own region throughout.

---

## Step 1 – Create the S3 Staging Bucket

Snapshots are uploaded here temporarily before Rekognition processes them.

```bash
REGION="ap-southeast-2"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET_NAME="ha-rekognition-staging-${ACCOUNT_ID}"

# Create the bucket
# NOTE: us-east-1 does NOT accept LocationConstraint – omit that flag if your region is us-east-1
aws s3api create-bucket \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"

# For us-east-1 only, use this instead:
# aws s3api create-bucket --bucket "$BUCKET_NAME" --region us-east-1

# Block all public access (recommended)
aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "Bucket created: $BUCKET_NAME"
```

> **Tip:** The bucket name must be globally unique. Using your AWS account number as a suffix ensures uniqueness and matches the default value shown in the add-on configuration.

---

## Step 2 – Create the Rekognition Face Collection

The collection is a persistent index of known faces that snapshots are searched against.

```bash
COLLECTION_ID="ha_known_people"

aws rekognition create-collection \
  --collection-id "$COLLECTION_ID" \
  --region "$REGION"
```

Expected output:

```json
{
    "StatusCode": 200,
    "CollectionArn": "aws:rekognition:ap-southeast-2:123456789012:collection/ha_known_people",
    "FaceModelVersion": "7.0"
}
```

---

## Step 3 – Create an IAM User with Least-Privilege Permissions

### 3a. Create the IAM policy

Save the following JSON to a file named `/tmp/ha-rekognition-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3StagingAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::${BUCKET_NAME}/snapshots/*"
    },
    {
      "Sid": "RekognitionRuntime",
      "Effect": "Allow",
      "Action": [
        "rekognition:DetectFaces",
        "rekognition:SearchFacesByImage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RekognitionEnrollment",
      "Effect": "Allow",
      "Action": [
        "rekognition:IndexFaces",
        "rekognition:ListFaces",
        "rekognition:DeleteFaces"
      ],
      "Resource": "arn:aws:rekognition:${REGION}:${ACCOUNT_ID}:collection/${COLLECTION_ID}"
    }
  ]
}
```

Replace `${BUCKET_NAME}`, `${REGION}`, `${ACCOUNT_ID}`, and `${COLLECTION_ID}` with your values. The path `snapshots/*` in the S3 ARN must match the `s3_prefix` add-on config option (default: `snapshots/`). Then create the policy using `envsubst`:

```bash
# Export the variables so envsubst can replace them in the policy template
export BUCKET_NAME REGION ACCOUNT_ID COLLECTION_ID

POLICY_DOC=$(envsubst < /tmp/ha-rekognition-policy.json)

POLICY_ARN=$(aws iam create-policy \
  --policy-name "HASSRekognitionPolicy" \
  --policy-document "$POLICY_DOC" \
  --query Policy.Arn \
  --output text)

echo "Policy ARN: $POLICY_ARN"
```

> **Note:** `envsubst` is available on Linux/macOS (part of `gettext`). If it is not installed, edit `/tmp/ha-rekognition-policy.json` manually to replace the placeholder values before running `aws iam create-policy --policy-document file:///tmp/ha-rekognition-policy.json`.

### 3b. Create the IAM user and attach the policy

```bash
IAM_USER="hass-rekognition"

aws iam create-user --user-name "$IAM_USER"

aws iam attach-user-policy \
  --user-name "$IAM_USER" \
  --policy-arn "$POLICY_ARN"
```

### 3c. Create an access key

```bash
aws iam create-access-key \
  --user-name "$IAM_USER" \
  --query 'AccessKey.{ID:AccessKeyId,Secret:SecretAccessKey}' \
  --output table
```

> **Important:** Save the `AccessKeyId` and `SecretAccessKey` immediately – the secret cannot be retrieved again after this point.

---

## Step 4 – Enroll Known Faces

You need at least one face in the collection before the add-on can return a `matched` result.

### Prepare a reference image

Use a clear, front-facing photo of the person (JPEG or PNG, minimum 80×80 px). Upload it to S3 first:

```bash
PERSON_NAME="john"   # Used as ExternalImageId – no spaces, lowercase recommended
IMAGE_FILE="/path/to/john.jpg"

aws s3 cp "$IMAGE_FILE" "s3://${BUCKET_NAME}/enroll/${PERSON_NAME}.jpg"
```

### Index the face into the collection

```bash
aws rekognition index-faces \
  --collection-id "$COLLECTION_ID" \
  --image "S3Object={Bucket=${BUCKET_NAME},Name=enroll/${PERSON_NAME}.jpg}" \
  --external-image-id "$PERSON_NAME" \
  --detection-attributes NONE \
  --region "$REGION"
```

The `ExternalImageId` value (`john` in this example) is what appears in the `name` field of the API response when that face is recognised.

### Verify enrolled faces

```bash
aws rekognition list-faces \
  --collection-id "$COLLECTION_ID" \
  --region "$REGION" \
  --query 'Faces[*].{ID:FaceId,Name:ExternalImageId}' \
  --output table
```

---

## Step 5 – Install and Configure the Add-on

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Add the custom repository: `https://github.com/JCalvi/HASSAddons`
3. Find **Rekognition Bridge** and click **Install**.
4. Open the **Configuration** tab and fill in your values:

```json
{
  "aws_access_key_id": "<AccessKeyId from Step 3c>",
  "aws_secret_access_key": "<SecretAccessKey from Step 3c>",
  "aws_region": "ap-southeast-2",
  "rekognition_collection": "ha_known_people",
  "s3_bucket": "ha-rekognition-staging-<your-account-id>",
  "s3_prefix": "snapshots/",
  "default_threshold": 95,
  "delete_after_match": true,
  "ha_url": "http://172.30.32.1:8123",
  "ha_token": "<your Home Assistant long-lived token>",
  "helper_person_name": "input_text.rekognition_person_name",
  "helper_person_similarity": "input_number.rekognition_person_similarity",
  "helper_person_status": "input_text.rekognition_person_status"
}
```

5. Copy `ha_examples/hass_rekognition.yaml` into your HA config directory and include it:

```yaml
# configuration.yaml
homeassistant:
  packages: !include hass_rekognition.yaml
```

6. Restart Home Assistant to load the new helpers, then start the add-on.

---

## Step 6 – Test the Integration

Send a test request from the Home Assistant terminal or from any machine on your network:

```bash
curl -s -X POST http://<ha-ip>:8080/match \
  -H "Content-Type: application/json" \
  -d '{"snapshot_path": "/media/snapshots/test.jpg", "threshold": 90}' \
  | python3 -m json.tool
```

Expected response when a face is recognised:

```json
{
  "status": "matched",
  "matched": true,
  "name": "john",
  "similarity": 98.72,
  "faces_detected": 1,
  "threshold": 90
}
```

Check the add-on log (**Settings → Add-ons → Rekognition Bridge → Log**) if you receive an `error` status.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `status: error` – `AccessDenied` | IAM policy missing a permission or wrong resource ARN | Re-check the policy in Step 3 and confirm the bucket/collection names match |
| `status: no_face` | Image quality too low, face too small, or not front-facing | Use a higher-resolution image; face should be ≥ 100 px wide |
| `status: no_match` | Face not in collection, or threshold too high | Enrol the face (Step 4) or lower `default_threshold` |
| Add-on won't start | Wrong `ha_url` or `ha_token` | Verify the URL is reachable from within the add-on container and the token is valid |
| `FileNotFoundError` | Snapshot path not accessible | Ensure the path is under `/media` (the add-on maps `media:ro`) |

---

## Cleaning Up

To remove all AWS resources created in this guide:

```bash
# Delete the Rekognition collection (removes all enrolled face data)
aws rekognition delete-collection --collection-id "$COLLECTION_ID" --region "$REGION"

# Empty and delete the S3 bucket
aws s3 rm "s3://${BUCKET_NAME}" --recursive
aws s3api delete-bucket --bucket "$BUCKET_NAME" --region "$REGION"

# Detach policy and delete IAM user
aws iam detach-user-policy --user-name "$IAM_USER" --policy-arn "$POLICY_ARN"
aws iam delete-access-key \
  --user-name "$IAM_USER" \
  --access-key-id "$(aws iam list-access-keys --user-name "$IAM_USER" --query 'AccessKeyMetadata[0].AccessKeyId' --output text)"
aws iam delete-user --user-name "$IAM_USER"
aws iam delete-policy --policy-arn "$POLICY_ARN"
```
