# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container to /app
WORKDIR /app

# Add the current directory contents into the container at /app
ADD . /app

# Install the GCC compiler
RUN apt-get update && apt-get install -y gcc

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make the script executable
RUN chmod +x start.sh

# Make port 80 available to the world outside this container
EXPOSE 80

# Run start.sh when the container launches
CMD ["./start.sh"]