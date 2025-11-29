# Dockerfile for kali_mcp MCP server (pinned-ish Kali base)
FROM kalilinux/kali-rolling

# keep noninteractive
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system packages and common pentest tooling
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip python3-venv python3-dev git wget unzip ca-certificates \
    nmap nikto sqlmap golang-go gobuster exploitdb tcpdump mitmproxy \
    binwalk openjdk-11-jre-headless ruby-full build-essential curl jq \
    unzip zip && \
    update-ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install python dependencies and gems
# Copy requirements in early for cache
COPY requirements.txt /tmp/requirements.txt

# Create a virtualenv and install Python deps into it
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt && \
    gem install wpscan --no-document || true

# Make sure the venv is used by default
ENV PATH="/opt/venv/bin:${PATH}"

# Install apktool (java) and jadx (decompiler)
RUN mkdir -p /opt/tools && \
    wget -q -O /opt/tools/apktool.jar https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool.jar || true && \
    wget -q -O /usr/local/bin/apktool https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool || true && \
    chmod +x /usr/local/bin/apktool || true && \
    wget -q -O /opt/tools/jadx.zip https://github.com/skylot/jadx/releases/download/v1.4.6/jadx-1.4.6.zip || true && \
    unzip -q /opt/tools/jadx.zip -d /opt/tools || true && \
    ln -s /opt/tools/jadx/bin/jadx /usr/local/bin/jadx || true

# Copy server code
WORKDIR /app
COPY kali_mcp_server.py /app/kali_mcp_server.py
# COPY readme.txt /app/readme.txt

# Run as root (removed non-root user creation)
# RUN useradd -m -u 1000 mcpuser && chown -R mcpuser:mcpuser /app

# USER mcpuser
# ENV PATH="/home/mcpuser/.local/bin:${PATH}"

# Expose a generic port (not strictly necessary for stdio transport but useful)
EXPOSE 8080

# Start server
CMD ["python3", "kali_mcp_server.py"]
