#!/usr/bin/env python3
"""Simple kali_mcp MCP Server - exposes common pentest tools via FastMCP"""

import os
import sys
import json
import logging
import shutil
import tempfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from mcp.server.fastmcp import FastMCP

# Logging -> stderr required
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("kali_mcp-server")

# Initialize MCP server (no prompt parameter)
# Use stateless_http=True for better HTTP transport support
mcp = FastMCP("kali_mcp_server", stateless_http=True)

# Configuration with sensible defaults (override with ENV)
JOB_TIMEOUT = int(os.environ.get("KALI_MCP_JOB_TIMEOUT", "600"))
CONCURRENT_PER_USER = int(os.environ.get("KALI_MCP_CONCURRENT_PER_USER", "3"))
ARTIFACT_TTL_DAYS = int(os.environ.get("KALI_MCP_ARTIFACT_TTL_DAYS", "7"))
ARTIFACT_MAX_MB = int(os.environ.get("KALI_MCP_ARTIFACT_MAX_MB", "200"))
ARTIFACT_STORE_TYPE = os.environ.get("KALI_MCP_ARTIFACT_STORE", "minio")  # minio | s3 | local
ARTIFACT_STORE_BUCKET = os.environ.get("KALI_MCP_BUCKET", "kali-mcp-artifacts")
ARTIFACT_LOCAL_PATH = os.environ.get("KALI_MCP_ARTIFACT_LOCAL", "/artifacts")
MINIO_ENDPOINT = os.environ.get("KALI_MCP_MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("KALI_MCP_MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("KALI_MCP_MINIO_SECRET_KEY", "minioadmin")
API_KEYS_CSV = os.environ.get("KALI_MCP_API_KEYS_CSV", "")  # optional CSV of key:role lines

# Simple in-memory RBAC & keys (persistent store optional)
API_KEYS = {}  # api_key -> role
if API_KEYS_CSV:
    try:
        for line in Path(API_KEYS_CSV).read_text().splitlines():
            if not line.strip():
                continue
            key, role = line.split(":", 1)
            API_KEYS[key.strip()] = role.strip()
    except Exception as e:
        logger.warning(f"Failed to load API keys CSV: {e}")

# Add a default admin key for quick testing (override in prod)
if not API_KEYS:
    API_KEYS["changeme_admin_key"] = "admin"
    API_KEYS["changeme_operator_key"] = "operator"

# S3 client for artifact uploads (supports MinIO)
def s3_client():
    cfg = Config(signature_version="s3v4")
    endpoint = MINIO_ENDPOINT if ARTIFACT_STORE_TYPE in ("minio",) else None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=cfg,
    )

def ensure_bucket():
    if ARTIFACT_STORE_TYPE in ("minio", "s3"):
        client = s3_client()
        try:
            client.head_bucket(Bucket=ARTIFACT_STORE_BUCKET)
        except ClientError:
            try:
                client.create_bucket(Bucket=ARTIFACT_STORE_BUCKET)
            except Exception as e:
                logger.error(f"Could not create bucket: {e}")

def upload_artifact_local(src_path, dest_name):
    dest_dir = Path(ARTIFACT_LOCAL_PATH)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    shutil.move(str(src_path), str(dest))
    url = f"file://{dest}"
    return url

def upload_artifact_s3(src_path, dest_name):
    client = s3_client()
    try:
        client.upload_file(str(src_path), ARTIFACT_STORE_BUCKET, dest_name)
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": ARTIFACT_STORE_BUCKET, "Key": dest_name},
            ExpiresIn=ARTIFACT_TTL_DAYS * 24 * 3600,
        )
        return url
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        return ""

def upload_artifact(src_path, dest_name):
    if ARTIFACT_STORE_TYPE in ("minio", "s3"):
        return upload_artifact_s3(src_path, dest_name)
    else:
        return upload_artifact_local(src_path, dest_name)

def run_command(cmd_list, cwd=None, timeout=60):
    """Run a command safely using argument list"""
    start = datetime.now(timezone.utc)
    try:
        logger.info(f"Running command: {' '.join(cmd_list)} in {cwd}")
        result = subprocess.run(
            cmd_list,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        end = datetime.now(timezone.utc)
        duration_ms = int((end - start).total_seconds() * 1000)
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired:
        end = datetime.now(timezone.utc)
        duration_ms = int((end - start).total_seconds() * 1000)
        return {"exit_code": -1, "stdout": "", "stderr": "⏱️ Command timed out", "duration_ms": duration_ms}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": f"❌ Error: {str(e)}", "duration_ms": 0}

def make_result(job_id, user_id, tool, status, exit_code, started_at, duration_ms, stdout, stderr, artifacts, tool_metadata=None, warnings=None):
    out = {
        "job_id": job_id,
        "user_id": user_id,
        "tool": tool,
        "status": status,
        "exit_code": exit_code,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "artifacts": artifacts or [],
        "tool_metadata": tool_metadata or {},
        "warnings": warnings or [],
    }
    return json.dumps(out)

def auth_from_headers(headers):
    # Simple header extraction; expect "x-api-key"
    api_key = headers.get("x-api-key") or headers.get("X-API-Key") or ""
    role = API_KEYS.get(api_key, "")
    return api_key, role

# --- Helper to create ephemeral job workspace and collect artifacts ---
def collect_and_upload_artifacts(workdir, job_id):
    artifacts = []
    p = Path(workdir)
    for f in p.glob("**/*"):
        if f.is_file():
            size_mb = f.stat().st_size / 1024.0 / 1024.0
            if size_mb > ARTIFACT_MAX_MB:
                logger.warning(f"Skipping large artifact: {f} ({size_mb:.2f} MB)")
                continue
            dest_name = f"{job_id}/{f.relative_to(p).as_posix()}"
            try:
                url = upload_artifact(str(f), dest_name)
                if url:
                    artifacts.append({"name": f.relative_to(p).as_posix(), "url": url, "size_mb": round(size_mb,2)})
            except Exception as e:
                logger.error(f"Upload failed for {f}: {e}")
    return artifacts

# === Tools exposed via FastMCP ===
# All parameters default to "" and docstrings are single-line only

@mcp.tool()
async def nmap_scan(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Run nmap scan against a target with optional ports."""
    if not target.strip():
        return "❌ Error: 'target' is required"
    try:
        to = int(timeout) if timeout.strip() else JOB_TIMEOUT
    except Exception:
        to = JOB_TIMEOUT
    started_at = datetime.now(timezone.utc).isoformat()
    tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
    cmd = ["nmap", "-oA", "nmap_output"]
    if ports.strip():
        cmd += ["-p", ports.strip()]
    if profile.strip():
        if profile.strip() == "quick":
            cmd += ["-T4", "-F"]
        elif profile.strip() == "full":
            cmd += ["-sV", "-sC", "-O"]
    cmd += [target.strip()]
    res = run_command(cmd, cwd=tmpdir, timeout=to)
    artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
    status = "success" if res["exit_code"] == 0 else "error"
    return make_result(job_id, user_id, "nmap", status, res["exit_code"], started_at, res["duration_ms"], res["stdout"], res["stderr"], artifacts)

@mcp.tool()
async def nikto_scan(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Run nikto webscan against a target."""
    if not target.strip():
        return "❌ Error: 'target' is required"
    try:
        to = int(timeout) if timeout.strip() else 300
    except Exception:
        to = 300
    started_at = datetime.now(timezone.utc).isoformat()
    tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
    # nikto expects a URL; if user provided host, add http://
    url = target.strip()
    if not url.startswith("http"):
        url = "http://" + url
    cmd = ["nikto", "-host", url, "-output", "nikto.txt"]
    res = run_command(cmd, cwd=tmpdir, timeout=to)
    artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
    status = "success" if res["exit_code"] == 0 else "error"
    return make_result(job_id, user_id, "nikto", status, res["exit_code"], started_at, res["duration_ms"], res["stdout"], res["stderr"], artifacts)

@mcp.tool()
async def sqlmap_scan(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Run sqlmap against provided target URL."""
    if not target.strip():
        return "❌ Error: 'target' is required"
    try:
        to = int(timeout) if timeout.strip() else 300
    except Exception:
        to = 300
    started_at = datetime.now(timezone.utc).isoformat()
    tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
    cmd = ["sqlmap", "-u", target.strip(), "--batch", "--output-dir", tmpdir]
    res = run_command(cmd, cwd=tmpdir, timeout=to)
    artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
    status = "success" if res["exit_code"] == 0 else "error"
    return make_result(job_id, user_id, "sqlmap", status, res["exit_code"], started_at, res["duration_ms"], res["stdout"], res["stderr"], artifacts)

@mcp.tool()
async def gobuster_scan(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Run gobuster dir bruteforce against a target using a wordlist."""
    if not target.strip():
        return "❌ Error: 'target' is required"
    wordlist = profile.strip() or "/usr/share/wordlists/dirb/common.txt"
    try:
        to = int(timeout) if timeout.strip() else 180
    except Exception:
        to = 180
    started_at = datetime.now(timezone.utc).isoformat()
    tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
    url = target.strip()
    if not url.startswith("http"):
        url = "http://" + url
    cmd = ["gobuster", "dir", "-u", url, "-w", wordlist, "-o", "gobuster.txt"]
    res = run_command(cmd, cwd=tmpdir, timeout=to)
    artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
    status = "success" if res["exit_code"] == 0 else "error"
    return make_result(job_id, user_id, "gobuster", status, res["exit_code"], started_at, res["duration_ms"], res["stdout"], res["stderr"], artifacts)

@mcp.tool()
async def searchsploit_find(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Run searchsploit against a term."""
    if not target.strip():
        return "❌ Error: 'target' is required (search term)"
    started_at = datetime.now(timezone.utc).isoformat()
    tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
    cmd = ["searchsploit", target.strip(), "--nmap"] if profile.strip() == "nmap" else ["searchsploit", target.strip()]
    res = run_command(cmd, cwd=tmpdir, timeout=60)
    artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
    status = "success" if res["exit_code"] == 0 else "error"
    return make_result(job_id, user_id, "searchsploit", status, res["exit_code"], started_at, res["duration_ms"], res["stdout"], res["stderr"], artifacts)

@mcp.tool()
async def binwalk_extract(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Run binwalk on a given file path present in mounted container."""
    if not target.strip():
        return "❌ Error: 'target' is required (path to file inside container)"
    if not Path(target.strip()).exists():
        return f"❌ Error: file not found: {target.strip()}"
    try:
        to = int(timeout) if timeout.strip() else 120
    except Exception:
        to = 120
    started_at = datetime.now(timezone.utc).isoformat()
    tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
    # copy target into tmpdir for safer processing
    try:
        shutil.copy(target.strip(), tmpdir)
    except Exception as e:
        return f"❌ Error copying file: {e}"
    fname = Path(target.strip()).name
    cmd = ["binwalk", "--extract", fname]
    res = run_command(cmd, cwd=tmpdir, timeout=to)
    artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
    status = "success" if res["exit_code"] == 0 else "error"
    return make_result(job_id, user_id, "binwalk", status, res["exit_code"], started_at, res["duration_ms"], res["stdout"], res["stderr"], artifacts)

@mcp.tool()
async def apk_static(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Run apktool and jadx decompilation on an APK present in container path."""
    if not target.strip():
        return "❌ Error: 'target' is required (path to APK inside container)"
    if not Path(target.strip()).exists():
        return f"❌ Error: file not found: {target.strip()}"
    try:
        to = int(timeout) if timeout.strip() else 300
    except Exception:
        to = 300
    started_at = datetime.now(timezone.utc).isoformat()
    tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
    try:
        shutil.copy(target.strip(), tmpdir)
    except Exception as e:
        return f"❌ Error copying APK: {e}"
    apk_name = Path(target.strip()).name
    # apktool
    cmd1 = ["apktool", "d", apk_name]
    res1 = run_command(cmd1, cwd=tmpdir, timeout=to)
    # jadx
    cmd2 = ["jadx", "-d", "jadx_out", apk_name]
    res2 = run_command(cmd2, cwd=tmpdir, timeout=to)
    artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
    combined_stdout = res1["stdout"] + "\n" + res2["stdout"]
    combined_stderr = res1["stderr"] + "\n" + res2["stderr"]
    exit_code = 0 if (res1["exit_code"] == 0 and res2["exit_code"] == 0) else 1
    status = "success" if exit_code == 0 else "error"
    return make_result(job_id, user_id, "apk_static", status, exit_code, started_at, res1["duration_ms"] + res2["duration_ms"], combined_stdout, combined_stderr, artifacts)

@mcp.tool()
async def health_check(user_id: str = "", job_id: str = "", target: str = "", ports: str = "", profile: str = "", timeout: str = "") -> str:
    """Return a simple JSON health status of the server."""
    started_at = datetime.now(timezone.utc).isoformat()
    status = {"service": "kali_mcp", "status": "ok", "tools": ["nmap","nikto","sqlmap","gobuster","searchsploit","binwalk","apktool","jadx"], "timestamp": started_at}
    return json.dumps(status)

# --- End of tools ---

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting kali_mcp MCP server...")
    logger.info("=" * 60)
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Environment MCP_TRANSPORT: {os.environ.get('MCP_TRANSPORT', 'not set')}")
    logger.info(f"Environment PORT: {os.environ.get('PORT', 'not set')}")
    logger.info(f"Environment HOST: {os.environ.get('HOST', 'not set')}")
    sys.stderr.flush()
    try:
        # Initialize bucket in background thread to avoid blocking startup
        def init_bucket_async():
            if ARTIFACT_STORE_TYPE in ("minio", "s3"):
                try:
                    ensure_bucket()
                    logger.info("Artifact bucket initialized successfully")
                except Exception as e:
                    logger.warning(f"Could not initialize artifact bucket (will retry on first use): {e}")
        
        import threading
        bucket_thread = threading.Thread(target=init_bucket_async, daemon=True)
        bucket_thread.start()
        logger.info("Bucket initialization thread started")
        sys.stderr.flush()
        
        # Check transport type and configure accordingly
        transport_type = os.environ.get("MCP_TRANSPORT", "stdio")
        
        if transport_type == "http":
            # HTTP transport for Smithery deployment (container runtime)
            port = int(os.environ.get("PORT", "8080"))
            host = os.environ.get("HOST", "0.0.0.0")
            logger.info(f"Starting MCP server with HTTP transport on {host}:{port}")
            sys.stderr.flush()
            
            # First, try FastMCP's built-in HTTP transport support
            try:
                logger.info("Attempting FastMCP's built-in HTTP transport...")
                sys.stderr.flush()
                # Try streamable-http first (recommended for stateless HTTP)
                mcp.run(transport="streamable-http", host=host, port=port)
                return  # Success!
            except (TypeError, ValueError, AttributeError) as e1:
                logger.info(f"streamable-http not supported: {e1}")
                try:
                    # Try regular http
                    mcp.run(transport="http", host=host, port=port)
                    return  # Success!
                except (TypeError, ValueError, AttributeError) as e2:
                    logger.info(f"http transport not supported: {e2}")
                    # Fall back to manual SSE setup
                    logger.info("Falling back to manual SSE transport setup...")
                    sys.stderr.flush()
            
            # Manual SSE transport setup (fallback)
            try:
                import uvicorn
                from mcp.server.sse import SseServerTransport
                from mcp.server import Server
                
                # FastMCP wraps a Server instance - we need to access it
                # FastMCP stores the server in the _server attribute
                server = None
                
                # Try to get the server from FastMCP
                if hasattr(mcp, '_server'):
                    server = mcp._server
                    logger.info("Found server via _server attribute")
                elif hasattr(mcp, 'server'):
                    server = mcp.server
                    logger.info("Found server via server attribute")
                else:
                    # Try to access through __dict__
                    mcp_dict = getattr(mcp, '__dict__', {})
                    for key, value in mcp_dict.items():
                        if isinstance(value, Server):
                            server = value
                            logger.info(f"Found server via __dict__['{key}']")
                            break
                
                if server is None:
                    # FastMCP might create server lazily - try calling run() in a way that initializes it
                    # Actually, let's just create a new Server and register tools manually
                    logger.warning("Could not access FastMCP's server, creating manual server")
                    logger.info("Creating new Server instance...")
                    sys.stderr.flush()
                    server = Server("kali_mcp_server")
                    logger.info("Server instance created")
                    sys.stderr.flush()
                    
                    # Register all tools manually
                    from mcp.types import Tool, TextContent
                    import inspect
                    
                    tools_dict = {}
                    tools_metadata = []
                    
                    tools_to_register = [
                        ("nmap_scan", nmap_scan, "Run nmap scan against a target with optional ports."),
                        ("nikto_scan", nikto_scan, "Run nikto webscan against a target."),
                        ("sqlmap_scan", sqlmap_scan, "Run sqlmap against provided target URL."),
                        ("gobuster_scan", gobuster_scan, "Run gobuster dir bruteforce against a target using a wordlist."),
                        ("searchsploit_find", searchsploit_find, "Run searchsploit against a term."),
                        ("binwalk_extract", binwalk_extract, "Run binwalk on a given file path present in mounted container."),
                        ("apk_static", apk_static, "Run apktool and jadx decompilation on an APK present in container path."),
                        ("health_check", health_check, "Return a simple JSON health status of the server."),
                    ]
                    
                    for tool_name, tool_func, tool_description in tools_to_register:
                        sig = inspect.signature(tool_func)
                        properties = {}
                        for param_name, param in sig.parameters.items():
                            if param_name == "self":
                                continue
                            param_type = "string"
                            if param.annotation != inspect.Parameter.empty:
                                if param.annotation == str:
                                    param_type = "string"
                                elif param.annotation == int:
                                    param_type = "integer"
                                elif param.annotation == bool:
                                    param_type = "boolean"
                            properties[param_name] = {"type": param_type, "description": ""}
                        
                        tools_dict[tool_name] = tool_func
                        tools_metadata.append(Tool(
                            name=tool_name,
                            description=tool_description,
                            inputSchema={"type": "object", "properties": properties, "required": []}
                        ))
                    
                    # Create a closure to capture tools_dict
                    tools_dict_final = tools_dict.copy()
                    
                    @server.call_tool()
                    async def handle_call_tool(name: str, arguments: dict):
                        if name in tools_dict_final:
                            tool_func = tools_dict_final[name]
                            result = await tool_func(**arguments)
                            return [TextContent(type="text", text=str(result))]
                        raise ValueError(f"Unknown tool: {name}")
                    
                    @server.list_tools()
                    async def handle_list_tools():
                        return tools_metadata
                    
                    logger.info(f"Created manual server with {len(tools_to_register)} tools")
                
                # Verify server is ready
                if server is None:
                    raise RuntimeError("Server instance is None - cannot start")
                
                logger.info("Server instance verified, creating SSE transport...")
                sys.stderr.flush()
                
                # Create SSE transport and run with uvicorn
                logger.info("Creating SSE transport with /mcp endpoint")
                sys.stderr.flush()
                
                try:
                    transport = SseServerTransport("/mcp")
                    logger.info("SseServerTransport created successfully")
                    sys.stderr.flush()
                    
                    app = transport.create_app(server)
                    logger.info("FastAPI app created from transport successfully")
                    sys.stderr.flush()
                    
                    # Add a simple health check endpoint for debugging
                    @app.get("/health")
                    async def health_check_endpoint():
                        return {"status": "ok", "service": "kali_mcp"}
                    
                    @app.get("/")
                    async def root():
                        return {"service": "kali_mcp", "mcp_endpoint": "/mcp"}
                    
                    logger.info("=" * 60)
                    logger.info(f"Starting uvicorn server on {host}:{port}")
                    logger.info(f"MCP endpoint: http://{host}:{port}/mcp")
                    logger.info(f"Health check: http://{host}:{port}/health")
                    logger.info("=" * 60)
                    sys.stderr.flush()
                    
                    # Start uvicorn - this blocks
                    # Use loop="asyncio" to ensure compatibility
                    uvicorn.run(
                        app, 
                        host=host, 
                        port=port, 
                        log_level="info", 
                        access_log=True,
                        loop="asyncio"
                    )
                except Exception as transport_error:
                    logger.error(f"Error in transport setup: {transport_error}")
                    import traceback
                    traceback.print_exc()
                    sys.stderr.flush()
                    raise
                
            except ImportError as e:
                logger.error(f"Required package missing: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
            except Exception as e:
                logger.error(f"Failed to start HTTP server: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
        else:
            # Stdio transport for local development
            logger.info("Starting MCP server with stdio transport")
            sys.stderr.flush()
            mcp.run()
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)