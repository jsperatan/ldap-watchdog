# Use an official Python runtime as the base image
FROM python:3.12

# Set the working directory inside the container
WORKDIR /app

# Copy the current directory contents (your Python script) into the container at /app
COPY . /app

# Install any necessary dependencies
RUN pip install --no-cache-dir ldap3 requests

# Make the script executable (optional)
RUN chmod +x ldap-watchdog.py

# Run the Python script when the container starts
CMD ["python", "ldap-watchdog.py"]

