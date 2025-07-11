# Example Python Dockerfile

FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install -r requirements.txt

# Set the SSL_CERT_FILE environment variable
ENV SSL_CERT_FILE=/usr/local/lib/python3.11/site-packages/certifi/cacert.pem

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
