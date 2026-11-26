# Rencana dan langkah deployment (AWS Academy Cloud Foundations Sandbox, us-east-1)

Dokumen ini mencatat langkah yang benar-benar dijalankan dari laptop (WSL, AWS CLI v2, Docker).
Sandbox menghapus semua resource di akhir setiap sesi, jadi langkah 1 sampai 6 dikerjakan dalam satu sesi.

## 0. Persiapan (setiap sesi)

1. Start Lab, lalu salin kredensial dari **Details → Show** (bagian AWS CLI) ke `~/.aws/credentials`.
   Kredensial ini rahasia dan berganti setiap sesi; jangan di-commit atau di-screenshot.
2. Atur region dan variabel:

```bash
aws configure set region us-east-1
aws sts get-caller-identity
export AWS_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export BUCKET=inventory-items-$ACCOUNT_ID
```

## 1. Pengecekan layanan (desain awal)

Desain awal memakai DynamoDB, ECR, dan API Gateway. Ketiganya ditolak sandbox:

| Perintah | Hasil |
| --- | --- |
| `aws dynamodb create-table --table-name InventoryItems ...` | `AccessDeniedException` (`dynamodb:CreateTable`) |
| `aws ecr create-repository --repository-name inventory-api` | `AccessDeniedException` (`ecr:CreateRepository`) |
| `aws apigatewayv2 create-api --name inventory-api --protocol-type HTTP` | `AccessDeniedException` (`apigateway:POST`) |

Penggantinya: S3 untuk penyimpanan, Lambda paket zip, dan Lambda Function URL. Arsitektur tetap sama.

## 2. Bucket S3 (pengganti DynamoDB)

```bash
aws s3api create-bucket --bucket $BUCKET
```

## 3. Fungsi Lambda (paket zip, LabRole)

```bash
find app -name __pycache__ -prune -exec rm -rf {} +
python3 -m zipfile -c /tmp/function.zip app/

aws lambda create-function \
  --function-name inventory-api \
  --runtime python3.12 \
  --handler app.handler.lambda_handler \
  --zip-file fileb:///tmp/function.zip \
  --role arn:aws:iam::$ACCOUNT_ID:role/LabRole \
  --timeout 10 --memory-size 256 \
  --environment "Variables={BUCKET_NAME=$BUCKET}"
aws lambda wait function-active-v2 --function-name inventory-api
```

Uji langsung:

```bash
aws lambda invoke --function-name inventory-api --cli-binary-format raw-in-base64-out \
  --payload file://events/create-item.json /tmp/out.json && cat /tmp/out.json
aws s3 ls s3://$BUCKET/items/
```

Hasil: `statusCode` 201 dan satu objek `items/<item_id>.json` di bucket.

## 4. Lambda Function URL (pengganti API Gateway)

```bash
aws lambda create-function-url-config --function-name inventory-api --auth-type NONE
aws lambda add-permission --function-name inventory-api --statement-id url-public \
  --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE
aws lambda add-permission --function-name inventory-api --statement-id url-invoke \
  --action lambda:InvokeFunction --principal '*' --invoked-via-function-url
export API_URL=$(aws lambda get-function-url-config --function-name inventory-api --query FunctionUrl --output text)
```

## 5. Uji konektivitas

```bash
bash scripts/smoke-test.sh | tee evidence/smoke-test.txt
```

Hasil: 201, 200, 200, 200, 200, 404, 400 (semua sesuai harapan).

## 6. Docker image (elemen Track B, diuji lokal karena ECR ditolak)

```bash
sudo docker build --platform linux/amd64 --provenance=false -t inventory-api:latest .
aws configure export-credentials --format env-no-export > /tmp/aws.env
sudo docker run -d --name inv-local -p 9000:8080 --env-file /tmp/aws.env \
  -e AWS_REGION=$AWS_REGION -e BUCKET_NAME=$BUCKET inventory-api:latest
sleep 3
curl -s -XPOST http://localhost:9000/2015-03-31/functions/function/invocations -d @events/create-item.json
sudo docker rm -f inv-local && rm -f /tmp/aws.env
```

Hasil: `statusCode` 201. Container memakai Lambda Runtime Interface Emulator bawaan base image, sehingga image yang sama
bisa dipakai Lambda bila ECR tersedia.

Catatan WSL: jika daemon Docker gagal dengan error `iptables ... nf_tables`, jalankan
`sudo update-alternatives --set iptables /usr/sbin/iptables-legacy` (dan `ip6tables`), lalu `sudo service docker start`.

## 7. Daftar bukti (`evidence/`)

| File | Isi |
| --- | --- |
| `00-access-denied.png` | Error penolakan DynamoDB, ECR, dan API Gateway |
| `01-identity.png` | `aws sts get-caller-identity` |
| `02-s3-bucket.png` | Bucket S3 dan objek di folder `items/` |
| `03-lambda-config.png`, `03-lambda-config-terminal.png` | Lambda `inventory-api`: runtime Python 3.12, paket zip, role LabRole, `BUCKET_NAME` |
| `04-function-url.png`, `04-function-url-terminal.png` | Function URL dengan auth type NONE |
| `05-smoke-test.png` dan `smoke-test.txt` | Hasil uji 4 endpoint CRUD |
| `06-docker-local.png` | Build dan uji Docker image secara lokal |

## Kembali ke desain awal (bila layanan tersedia)

Di akun yang mengizinkan DynamoDB, ECR, dan API Gateway, ikuti desain awal: buat tabel `InventoryItems`
(kunci `item_id`), push image ke ECR, buat Lambda dari image dengan `TABLE_NAME=InventoryItems`, lalu buat HTTP API
dengan rute `POST/GET /items` dan `GET/PUT/DELETE /items/{item_id}`. Kode aplikasi tidak perlu diubah.