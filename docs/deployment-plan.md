# Deployment plan (AWS Learner Lab, us-east-1)

Everything below uses the AWS CLI with Learner Lab credentials. Each step also says which screenshot to take as evidence.
The commands were written against the AWS documentation and have **not** been run against a live Learner Lab account yet,
so check each step's output before moving on. Resource names can be changed, but keep them consistent.

## 0. Prerequisites (once per lab session)

1. Start the lab and check the budget at the top of the lab page (screenshot: remaining budget).
2. Click **AWS Details** → **AWS CLI: Show**, copy the block into `~/.aws/credentials`. It contains a session token and changes every session.
3. Set the region and verify the identity:

```bash
export AWS_REGION=us-east-1
aws configure set region $AWS_REGION
aws --version
aws sts get-caller-identity          # screenshot: shows the account and the assumed LabRole
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REPO=inventory-api
export ECR_URI=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO
```

4. Open the Lambda, API Gateway, ECR, and DynamoDB consoles once to confirm they are available in your lab.
   If API Gateway is blocked, use a Lambda Function URL instead (see "Fallback").

## 1. DynamoDB table

```bash
aws dynamodb create-table \
  --table-name InventoryItems \
  --attribute-definitions AttributeName=item_id,AttributeType=S \
  --key-schema AttributeName=item_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
aws dynamodb describe-table --table-name InventoryItems --query 'Table.TableStatus'
```

Evidence: console screenshot of the table with partition key `item_id`.

## 2. ECR repository

```bash
aws ecr create-repository --repository-name $ECR_REPO --image-scanning-configuration scanOnPush=true
```

Evidence: repository list screenshot.

## 3. Build and push the Docker image

On Linux, prefix `docker` with `sudo` if your user is not in the `docker` group.

```bash
aws ecr get-login-password | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
docker build --platform linux/amd64 --provenance=false -t $ECR_REPO:latest .
docker tag $ECR_REPO:latest $ECR_URI:latest
docker push $ECR_URI:latest
```

- `--platform linux/amd64` matches the default Lambda architecture (important on ARM laptops).
- `--provenance=false` avoids an image manifest format that Lambda can reject. If your Docker does not support the flag, drop it.

Optional local check of the image (needs credentials in the environment and the table from step 1):

```bash
docker run --rm -p 9000:8080 -e TABLE_NAME=InventoryItems -e AWS_REGION \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN $ECR_REPO:latest
# in another terminal:
curl -s -XPOST http://localhost:9000/2015-03-31/functions/function/invocations -d @events/create-item.json
```

Evidence: `docker push` output and the ECR console showing the `latest` image.

## 4. Lambda function (container image, LabRole)

```bash
aws lambda create-function \
  --function-name inventory-api \
  --package-type Image \
  --code ImageUri=$ECR_URI:latest \
  --role arn:aws:iam::$ACCOUNT_ID:role/LabRole \
  --timeout 10 --memory-size 256 \
  --environment "Variables={TABLE_NAME=InventoryItems}"
aws lambda wait function-active-v2 --function-name inventory-api
```

Evidence: Lambda console showing package type **Image** and execution role **LabRole**.

Direct function test (before API Gateway exists):

```bash
aws lambda invoke --function-name inventory-api --cli-binary-format raw-in-base64-out \
  --payload file://events/create-item.json /tmp/out.json && cat /tmp/out.json
```

Evidence: the output showing `statusCode` 201.

## 5. API Gateway (HTTP API) with four routes

```bash
export LAMBDA_ARN=$(aws lambda get-function --function-name inventory-api --query 'Configuration.FunctionArn' --output text)
export API_ID=$(aws apigatewayv2 create-api --name inventory-api --protocol-type HTTP --query ApiId --output text)
export INTEGRATION_ID=$(aws apigatewayv2 create-integration --api-id $API_ID \
  --integration-type AWS_PROXY --integration-uri $LAMBDA_ARN --payload-format-version 2.0 \
  --query IntegrationId --output text)

for ROUTE in 'POST /items' 'GET /items' 'GET /items/{item_id}' 'PUT /items/{item_id}' 'DELETE /items/{item_id}'; do
  aws apigatewayv2 create-route --api-id $API_ID --route-key "$ROUTE" --target integrations/$INTEGRATION_ID
done

aws apigatewayv2 create-stage --api-id $API_ID --stage-name '$default' --auto-deploy

aws lambda add-permission --function-name inventory-api --statement-id apigw-invoke \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:$AWS_REGION:$ACCOUNT_ID:$API_ID/*"

export API_URL=https://$API_ID.execute-api.$AWS_REGION.amazonaws.com
echo $API_URL
```

Evidence: API Gateway console showing the routes and the Lambda integration.

## 6. Connectivity test

```bash
mkdir -p evidence
API_URL=$API_URL ./scripts/smoke-test.sh | tee evidence/smoke-test.txt
```

The script creates, reads, updates, lists, and deletes an item and prints the HTTP status of each call.
Expected statuses: 201, 200, 200, 200, 200, 404, 400.

Evidence: `evidence/smoke-test.txt` and a screenshot of the terminal. Optional: CloudWatch Logs screenshot for `/aws/lambda/inventory-api`.

## 7. Wrap up

- Take screenshots into `evidence/` and commit them.
- The resources used here have no hourly cost when idle, so there is nothing to stop. Check the budget again before ending the lab (screenshot).
- After the work is graded, delete the resources:

```bash
aws apigatewayv2 delete-api --api-id $API_ID
aws lambda delete-function --function-name inventory-api
aws ecr delete-repository --repository-name $ECR_REPO --force
aws dynamodb delete-table --table-name InventoryItems
```

## Fallback if API Gateway is not available

```bash
aws lambda create-function-url-config --function-name inventory-api --auth-type NONE
aws lambda add-permission --function-name inventory-api --statement-id url-public \
  --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE
```

Then use the printed `FunctionUrl` as `API_URL` (the handler routes on method and path, so the same endpoints work).
Update the architecture diagram and design brief to say "Lambda Function URL" instead of "API Gateway".

## Suggested commit sequence (commit as you really do each step)

1. `docs: add README and design brief draft`
2. `docs: add architecture diagram`
3. `feat: add Lambda handler and DynamoDB repository`
4. `test: add unit tests for handler and repository`
5. `build: add Dockerfile for Lambda container image`
6. `docs: add deployment plan and smoke-test script`
7. `chore: provision DynamoDB table and ECR repo (evidence screenshots)`
8. `deploy: push image, create Lambda and HTTP API (evidence)`
9. `test: add smoke-test output from deployed API`
10. `docs: finalize README and design brief`
