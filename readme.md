# kali_mcp MCP Server

A Model Context Protocol (MCP) server that exposes common pentest tools (nmap, nikto, sqlmap, gobuster, searchsploit, binwalk, apktool/jadx, etc.) as FastMCP tools. Each tool accepts a strict JSON payload through the MCP protocol and returns a structured JSON result (stringified) including job metadata and artifact signed URLs.

## Purpose

This MCP server provides a secure, reproducible environment for running controlled pentest tooling for educational and internal testing purposes.

## Features

- Exposes tools: nmap, nikto, sqlmap, gobuster, searchsploit, binwalk, apktool + jadx, plus a simple health_check tool.
- Each tool accepts parameters: user_id, job_id, target, ports/options, profile, timeout.
- Input sanitization and argument-list execution (no shell interpolation).
- Per-job ephemeral workspace (temporary directory) and artifact collection.
- Artifact upload to S3/MinIO (default) or local file path. Signed URLs are generated for downloads.
- Basic API key authentication (via x-api-key header) and simple RBAC.
- Configurable via environment variables.
- Dockerized for reproducible environment.

## Quick environment variables

- KALI_MCP_JOB_TIMEOUT: default 600
- KALI_MCP_CONCURRENT_PER_USER: default 3
- KALI_MCP_ARTIFACT_TTL_DAYS: default 7
- KALI_MCP_ARTIFACT_MAX_MB: default 200
- KALI_MCP_ARTIFACT_STORE: minio | s3 | local (default: minio)
- KALI_MCP_BUCKET: artifact bucket name (default: kali-mcp-artifacts)
- KALI_MCP_MINIO_ENDPOINT: default http://minio:9000
- KALI_MCP_MINIO_ACCESS_KEY / KALI_MCP_MINIO_SECRET_KEY: credentials
- KALI_MCP_API_KEYS_CSV: optional path with api_key:role lines

## Usage examples

Example tool invocation (MCP JSON via stdio transport):

```
{“jsonrpc”:“2.0”,“method”:“tool:nmap_scan”,“params”:{“user_id”:“alice”,“job_id”:“job-123”,“target”:“example.com”,“ports”:“1-1024”,“profile”:“quick”,“timeout”:“120”},“id”:1}
```

Tool returns a string containing JSON result:

```
{“job_id”:“job-123”,“user_id”:“alice”,“tool”:“nmap”,“status”:“success”, … }
```

## Security notes

- Do NOT expose this server publicly without proper network controls.
- Rotate API keys and move to a secure secrets store for production.
- Artifacts containing sensitive information should be purged per retention policy.

## License

MIT
