FROM python:3.14-slim-bookworm

# Install necessary packages including chromium and xvfb for seleniumbase
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    xvfb \
    xauth \
    libnss3 \
    libgconf-2-4 \
    procps \
    python3-tk \
    python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set up the working directory inside the container
WORKDIR /app

# Copy requirement and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip

# Copy all the scripts and app files
COPY . .

# Ensure run.sh is executable
RUN chmod +x run.sh

# Expose port 8080 for the web server
EXPOSE 8080

# Use the bash script as entrypoint
CMD ["./run.sh"]
