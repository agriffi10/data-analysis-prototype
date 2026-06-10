# Bootstrap: OpenTofu Remote State

OpenTofu stores its state in S3 and uses a DynamoDB table for state locking.
These two resources must be created **once**, manually, before `tofu init` can run.
They are intentionally **not** managed by OpenTofu itself — destroying them would lose
the state that tracks all other resources.

---

## Step 1 — Create the state S3 bucket

Choose a globally unique bucket name (e.g. `dat-prod-tf-state`).

```bash
STATE_BUCKET="dat-prod-tf-state"
AWS_REGION="us-east-1"

aws s3api create-bucket \
  --bucket "$STATE_BUCKET" \
  --region "$AWS_REGION" \
  --create-bucket-configuration LocationConstraint="$AWS_REGION"

# Enable versioning so state history is recoverable
aws s3api put-bucket-versioning \
  --bucket "$STATE_BUCKET" \
  --versioning-configuration Status=Enabled

# Block all public access
aws s3api put-public-access-block \
  --bucket "$STATE_BUCKET" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Enable server-side encryption
aws s3api put-bucket-encryption \
  --bucket "$STATE_BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
  }'
```

---

## Step 2 — Create the DynamoDB lock table

```bash
LOCK_TABLE="dat-prod-tf-state-lock"

aws dynamodb create-table \
  --table-name "$LOCK_TABLE" \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "$AWS_REGION"
```

---

## Step 3 — Create backend.conf

Copy `backend.conf.example` to `backend.conf` (gitignored) and fill in your values:

```bash
cp backend.conf.example backend.conf
```

Update `infra/backend.conf`

---

## Step 4 — Initialise OpenTofu

From the `infra/` directory:

```bash
tofu init -backend-config=backend.conf
```

After a successful `tofu init`, commit the generated `.terraform.lock.hcl` to the repo
to pin provider versions for all team members.

---

## Notes

- The state bucket and lock table are **not** in OpenTofu state. Do not attempt to import
  or manage them with `tofu`.
- The `terraform.tfvars` file (copied from `terraform.tfvars.example`) is gitignored.
  Store it in your secrets manager or share it via a secure channel.
- If you need to rotate or rename the state bucket, migrate state first using
  `tofu state push` / `tofu state pull` — do not delete the bucket until state is safely
  copied to the new location.
