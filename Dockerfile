FROM openapitools/openapi-generator-cli:v7.10.0 AS openapi-generator

WORKDIR /work
COPY docs/openapi.yaml /work/docs/openapi.yaml
RUN java -jar /opt/openapi-generator/modules/openapi-generator-cli/target/openapi-generator-cli.jar generate \
    -i /work/docs/openapi.yaml \
    -g python-fastapi \
    -o /work/app/generated/openapi \
    --additional-properties=packageName=generated_server

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=openapi-generator /work/app/generated/openapi /app/app/generated/openapi
RUN python scripts/postprocess_generated_openapi.py

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
