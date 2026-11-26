# Design Brief – Inventory API (Cloud Computing, Week 12)

Author: `<your name, student ID>` · Date: `<submission date>`

## 1. Use case

An inventory service for tracking items (for example lab equipment): add an item, look it up, update its quantity or location,
and remove it. Users are small teams who need a simple shared stock list that is available over HTTP without running a server.

## 2. Chosen track

**Track C – Serverless**, with **Track B elements**. API Gateway (HTTP API) routes requests to one Lambda function written in
Python 3.12. The function is packaged as a **Docker image** stored in a private **Amazon ECR** repository, and data is stored
in **DynamoDB**. Two services are planned: `inventory-api` (built in this stage) and `stock-alert` (planned only; it would
notify when stock falls below the minimum). Serverless was chosen because it keeps the Learner Lab budget nearly untouched:
there is no instance or database that bills while idle.

## 3. Architecture

See `docs/architecture.png`.

- **Request flow:** client → HTTPS → API Gateway HTTP API → Lambda `inventory-api` → DynamoDB `InventoryItems`.
- **Build flow:** laptop (`docker build`, `docker push`) → ECR private repository → image used by the Lambda function.
- **Logs:** Lambda writes to CloudWatch Logs.
- **IAM:** the Lambda function runs with the Learner Lab **LabRole**, which grants access to DynamoDB and CloudWatch Logs.
- **Network:** the function runs outside a VPC; clients reach it only through the API Gateway HTTPS endpoint. No NAT Gateway or load balancer is used.
- **Region:** us-east-1 (one of the two regions allowed in Learner Lab).

## 4. Data entity

`item` – table `InventoryItems`, partition key `item_id` (string, UUID).

| Field | Type | Notes |
| --- | --- | --- |
| item_id | string | generated |
| name | string | required |
| category | string | optional |
| quantity | integer | >= 0 |
| location | string | optional |
| min_stock | integer | >= 0 |
| updated_at | string | ISO 8601 UTC |

## 5. CRUD endpoints

| Operation | Method and path | Success | Errors |
| --- | --- | --- | --- |
| Create | POST /items | 201 | 400 |
| Read | GET /items/{item_id} | 200 | 404 |
| Update | PUT /items/{item_id} | 200 | 400, 404 |
| Delete | DELETE /items/{item_id} | 200 | 404 |

`GET /items` (list) is an additional endpoint.

## 6. Security

- Execution role: LabRole (no new IAM roles in Learner Lab).
- HTTPS only through API Gateway; input is validated (required name, non-negative integers, maximum text length).
- Private ECR repository; credentials are never committed (`.gitignore`).
- Known limitation: the API has no authentication in this stage. API keys or an authorizer are a later improvement.

## 7. Budget plan

Pay-per-request services only (API Gateway, Lambda, DynamoDB on-demand) plus one small ECR image. Expected cost for the
tests is a small fraction of a dollar (estimate; verify in the AWS Pricing Calculator). The remaining budget is checked at the
start and end of every lab session and screenshotted. Avoided on purpose: EC2 left running, RDS, NAT Gateway, load balancer.

## 8. Deployment plan and evidence

Steps and commands are in `docs/deployment-plan.md`: DynamoDB table → ECR repository → build and push image → Lambda from image
→ HTTP API with routes → `scripts/smoke-test.sh`. Evidence kept in `evidence/`: screenshots of the table, ECR image, Lambda
configuration (Image, LabRole), API Gateway routes, and the smoke-test output with HTTP status codes.

## 9. Risks

- API Gateway may not be available in a given Learner Lab; fallback is a Lambda Function URL.
- Docker image format issues on ARM laptops; mitigated by building for `linux/amd64`.
- Learner Lab sessions last at most 4 hours and the CLI credentials change each session.
