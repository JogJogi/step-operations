FROM cadquery/cadquery:2.4.0

WORKDIR /app

# Install additional dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir fastapi uvicorn[standard] python-multipart scipy numpy trimesh

RUN mkdir -p /data/uploads

COPY app/ ./

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
