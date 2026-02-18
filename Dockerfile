FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tmux \
    iproute2 \
    procps \
    psmisc \
    sudo \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.4/ttyd.x86_64 -o /usr/bin/ttyd \
    && chmod +x /usr/bin/ttyd \
    && groupadd -g 1002 w3c_offical \
    && groupadd -g 988 docker \
    && useradd -u 1001 -g 1002 -G sudo,docker w3c_offical \
    && echo "w3c_offical ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 14444

USER w3c_offical
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "14444", "--reload"]
