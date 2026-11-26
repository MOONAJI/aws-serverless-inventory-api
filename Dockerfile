# AWS-provided Lambda base image for Python 3.12 (includes boto3 and the Lambda runtime interface client).
FROM public.ecr.aws/lambda/python:3.12

# Application code only; no extra dependencies are needed.
COPY app/ ${LAMBDA_TASK_ROOT}/app/

# Handler: module app/handler.py, function lambda_handler
CMD ["app.handler.lambda_handler"]
