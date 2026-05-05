FROM python:3.9-slim

WORKDIR /app

# Install dependencies
RUN pip install flask requests basyx-python-sdk

# Copy application code
COPY . .

# Expose port (must match docker-compose mapping)
EXPOSE 5000

# Run the Flask app
CMD ["python", "app.py"]
