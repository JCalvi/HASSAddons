# Rekognition Bridge – AWS Quickstart Guide

This guide walks you through the minimum AWS setup required to run the **Rekognition Bridge** Home Assistant app from scratch.

---

## Quick Checklist

- [ ] AWS account with Rekognition and S3 access
- [ ] Private S3 bucket in your target region, with Block Public Access and default encryption
- [ ] One-day snapshot-prefix lifecycle rule, including noncurrent-version cleanup if versioned
- [ ] Rekognition face collection created
- [ ] IAM user created with least-privilege policy
- [ ] Access key generated and saved
- [ ] Purpose, AWS processing, consent and deletion procedure explained before enrollment
- [ ] At least one consenting person's face enrolled in the collection
- [ ] App installed and configured in Home Assistant
- [ ] *(Recommended)* API token configured + stored in `secrets.yaml`

---

## Prerequisites

- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) installed and configured (`aws configure`)
- An AWS account with billing enabled
- The region you plan to use – this guide uses **`ap-southeast-2`** (Sydney). Replace it with your own region throughout.

---

Run the setup and deletion commands with an administrative/operator AWS CLI profile that can manage these resources. The credentials entered into the app are for runtime access; do not use the app's credentials as an unrestricted account administrator. Do not run these examples against unrelated production buckets.

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

# Keep the staging bucket private
aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "Bucket created: $BUCKET_NAME"
```

> **Tip:** The bucket name must be globally unique. Using your AWS account number as a suffix ensures uniqueness and matches the default value shown in the app configuration.

---

### Default encryption

New S3 buckets already use SSE-S3 by default. For a **new dedicated staging bucket**, explicitly configure and verify that setting:

```bash
aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api get-public-access-block --bucket "$BUCKET_NAME"
aws s3api get-bucket-encryption --bucket "$BUCKET_NAME"
```

Do not overwrite an existing bucket's KMS/encryption configuration to follow this example. Review its existing policy and required KMS permissions instead.

### Staging bucket retention backstop

Keep `delete_after_match: true` for immediate best-effort cleanup after processing. A crashed/timed-out worker or failed S3 deletion can leave an object behind, so add a lifecycle rule scoped to the **configured snapshot prefix**, normally `snapshots/`.

The following configuration is for a **new dedicated bucket with no existing lifecycle rules**. `put-bucket-lifecycle-configuration` replaces the entire configuration: merge the rules into an existing configuration instead of overwriting unrelated rules. The example also expires noncurrent snapshot versions and removes expired delete markers if versioning is enabled or suspended.

```bash
cat > /tmp/rekognition-staging-lifecycle.json <<'JSON'
{
  "Rules": [
    {
      "ID": "ExpireRekognitionSnapshots",
      "Status": "Enabled",
      "Filter": {"Prefix": "snapshots/"},
      "Expiration": {"Days": 1},
      "NoncurrentVersionExpiration": {"NoncurrentDays": 1}
    },
    {
      "ID": "RemoveExpiredSnapshotDeleteMarkers",
      "Status": "Enabled",
      "Filter": {"Prefix": "snapshots/"},
      "Expiration": {"ExpiredObjectDeleteMarker": true}
    }
  ]
}
JSON

aws s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET_NAME" \
  --lifecycle-configuration file:///tmp/rekognition-staging-lifecycle.json

aws s3api get-bucket-lifecycle-configuration --bucket "$BUCKET_NAME"
aws s3api get-bucket-versioning --bucket "$BUCKET_NAME"
```

Change **both prefixes** to match `s3_prefix` if you use a different value. These rules permanently delete eligible snapshots/versions; keep enrollment/reference images outside that prefix.

S3 calculates expiration dates using UTC day boundaries and processes deletion asynchronously. One-day expiration is **not guaranteed deletion within 24 hours**. For versioned buckets, current-object deletion can create a delete marker while retaining the old version; the noncurrent-version rule handles that additional retention. Object Lock or other retention controls can prevent permanent deletion.

These rules do not remove local Home Assistant snapshots, the `enroll/` prefix, enrolled Rekognition face vectors, or service-side copies described in the Rekognition FAQ.

References: [S3 expiration behaviour](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html), [lifecycle CLI](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-bucket-lifecycle-configuration.html), [default encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-encryption.html).

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

Replace `${BUCKET_NAME}`, `${REGION}`, `${ACCOUNT_ID}`, and `${COLLECTION_ID}` with your values. The path `snapshots/*` in the S3 ARN must match the `s3_prefix` app config option (default: `snapshots/`). Then create the policy using `envsubst`:

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

You need at least one face in the collection before the app can return a `matched` result.

Explain the purpose, the fact that images are sent to AWS, retention and deletion before enrolling anyone. Obtain informed consent and check the requirements applicable to your use. Do not enrol visitors or housemates without their knowledge. See [AWS biometric notice and consent terms](https://aws.amazon.com/legal/biometric-notice-and-consent-terms/).

Use a reference photo containing only the intended person. Keep an inventory of the returned FaceIds and their ExternalImageId so every reference image for a person can be removed later. Face vectors/metadata persist until deleted; deleting the source photo does not delete the enrollment.

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

### Remove the uploaded reference image

Once indexing has succeeded, remove the source image from `enroll/` if you do not need to retain it:

```bash
aws s3 rm "s3://${BUCKET_NAME}/enroll/${PERSON_NAME}.jpg"
```

In a versioned bucket this normal delete can leave noncurrent versions; inspect and remove those using an operator's version-aware deletion process. The `snapshots/` lifecycle rules do not apply to `enroll/`. Also manage the local reference file and any backups.

### Remove an enrolled person

Use your operator AWS CLI profile, not a public-facing HTTP endpoint. First list all faces (the CLI paginates automatically unless pagination is disabled):

```bash
aws rekognition list-faces \
  --collection-id "$COLLECTION_ID" \
  --region "$REGION" \
  --query 'Faces[*].{FaceId:FaceId,Name:ExternalImageId}' \
  --output table
```

Identify **every FaceId** belonging to the intended person, including images enrolled under alternate names. Check the selected IDs before deleting. Replace the placeholders below with those actual IDs; do not delete the whole shared collection to remove one person.

```bash
aws rekognition delete-faces \
  --collection-id "$COLLECTION_ID" \
  --region "$REGION" \
  --face-ids FACE_ID_1 FACE_ID_2
```

Supply only the IDs needed (one is sufficient for a single entry); use batches of at most 4,096 IDs. Review both `DeletedFaces` and `UnsuccessfulFaceDeletions`, then list faces again and verify all intended entries are gone. `ExternalImageId` is a label, not a unique FaceId, so a person may have several entries.

Remove any retained enrollment photos, local snapshots, notification copies, logs and backups according to your retention/deletion policy. These are separate from the collection and S3 staging cleanup. See [DeleteFaces](https://docs.aws.amazon.com/cli/latest/reference/rekognition/delete-faces.html). Review the [Rekognition FAQ](https://aws.amazon.com/rekognition/faqs/) for service-side input retention, AWS Organizations AI-services opt-out and AWS Support deletion-request options; these commands alone do not remove every possible copy.

---

## Step 5 – Install and Configure the App

1. In Home Assistant, go to **Settings → Apps → App Store**.
2. Add the custom repository: `https://github.com/JCalvi/HASSAddons`
3. Find **Rekognition Bridge** and click **Install**.
4. Open the **Configuration** tab and fill in your values (plus recommended security settings):

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
  "helper_person_name": "input_text.rekognition_person_name",
  "helper_person_similarity": "input_number.rekognition_person_similarity",
  "helper_person_status": "input_text.rekognition_person_status",
  "worker_timeout": 60,
  "log_worker_stderr": false,
  "api_token": "<your-long-random-token>"
}
```

5. Copy `ha_examples/hass_rekognition.yaml` into your HA config directory and include it:

```yaml
# configuration.yaml
homeassistant:
  packages: !include hass_rekognition.yaml
```

6. Add the API token to your Home Assistant `secrets.yaml`:

```yaml
rekognition_bridge_token: "<your-long-random-token>"
```

7. Restart Home Assistant to load the new helpers, then start the app.

---

## Step 6 – Test the Integration

Send a test request from the Home Assistant terminal or from any machine on your network.

If `api_token` is set in the app, include the `X-Rekognition-Token` header:

```bash
curl -s -X POST http://<ha-ip>:8080/match \
  -H "Content-Type: application/json" \
  -H "X-Rekognition-Token: <your-long-random-token>" \
  -d '{"snapshot_path": "/media/snapshots/test.jpg", "threshold": 95}' \
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

Check the app log (**Settings → Apps → Rekognition Bridge → Log**) if you receive an `error` status.

---

## Event-driven automation, errors and cost

Use the [notification-only example](ha_examples/automations.yaml) for person-detected and/or doorbell events. It uses a shared cooldown and single-run mode; it does not poll on a timer or upload a video stream. Create/allow the chosen snapshot directory first. Copy the example's automation list into your existing automation configuration without duplicating the top-level `automation:` key.

A match is a **hint**, not proof of identity or a liveness check. Use an appropriately high threshold for your notification use, test lighting/angles and review false matches. Do not use facial recognition alone to unlock a door or disarm an alarm. The example contains no access-control action.

The example only accepts the **current request's** HTTP 200 JSON response with `status: matched`, `matched: true`, a nonempty name and a score meeting the requested threshold. No face, no match, malformed output, errors and timeouts never produce a matched-person action. Other consequential workflows must require independent authentication/approval and leave the protected action unperformed on failure. Never treat a previously successful helper state as the new request's result.

The maintainer measured **under one second from the automation call to the result on his installation**. Camera capture and notification delivery outside that call are separate. This is not a latency guarantee; no representative daily snapshot count or monthly bill has been published.

To estimate your own bill, count actual recognition requests over representative days. The worker calls DetectFaces once per uploaded snapshot and SearchFacesByImage once if a face is detected, before retries. For example, **10 snapshots/day for 30 days**, all containing faces, gives **300 calls to each API (600 total)**; **100/day** gives **3,000 to each (6,000 total)**. These are illustrative volumes, not measured usage. Apply [current regional pricing](https://aws.amazon.com/rekognition/pricing/), adding vector storage, enrollment, S3 requests/storage, retries, applicable transfer and other enabled services. Budget alerts help monitor spending but are not a hard cap.

Measure your installation with an automation trace or curl's `--write-out '\\nHTTP %{http_code}; total %{time_total}s\\n'` option on the test request. Do not publish tokens or face data in timing reports. A timed-out request may already have incurred AWS usage; retrying can add calls.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Unauthorized` | `api_token` is set in the app but request header missing/wrong | Ensure `X-Rekognition-Token` matches the app `api_token` value; if using HA, ensure the `!secret rekognition_bridge_token` is defined |
| `status: error` – `AccessDenied` | IAM policy missing a permission or wrong resource ARN | Re-check the policy in Step 3 and confirm the bucket/collection names match |
| `status: no_face` | Image quality too low, face too small, or not front-facing | Use a higher-resolution image; face should be ≥ 100 px wide |
| `status: no_match` | Face not in collection, image unsuitable, or threshold not met | Check enrollment, lighting and camera angle before adjusting the threshold; do not lower it to permit access |
| `FileNotFoundError` | Snapshot path not accessible | Ensure the path is under `/media` (the app maps `media:ro`) |

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
