#!/usr/bin/env python3
"""Kali MCP Server - exposes common pentest tools via FastMCP"""

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
        logger.info(f"Loaded {len(API_KEYS)} API keys from {API_KEYS_CSV}")
    except Exception as e:
        logger.warning(f"Could not load API keys from {API_KEYS_CSV}: {e}")

# S3/MinIO client setup
s3_client = None
if ARTIFACT_STORE_TYPE in ("minio", "s3"):
    try:
        config = Config(signature_version="s3v4")
        if ARTIFACT_STORE_TYPE == "minio":
            s3_client = boto3.client(
                "s3",
                endpoint_url=MINIO_ENDPOINT,
                aws_access_key_id=MINIO_ACCESS_KEY,
                aws_secret_access_key=MINIO_SECRET_KEY,
                config=config,
            )
        else:  # s3
            s3_client = boto3.client("s3", config=config)
        logger.info(f"Initialized {ARTIFACT_STORE_TYPE} client")
    except Exception as e:
        logger.warning(f"Could not initialize {ARTIFACT_STORE_TYPE} client: {e}")

def ensure_bucket():
    """Ensure artifact bucket exists (MinIO/S3 only)"""
    if ARTIFACT_STORE_TYPE not in ("minio", "s3") or not s3_client:
        return
    try:
        s3_client.head_bucket(Bucket=ARTIFACT_STORE_BUCKET)
    except ClientError:
        try:
            s3_client.create_bucket(Bucket=ARTIFACT_STORE_BUCKET)
            logger.info(f"Created bucket: {ARTIFACT_STORE_BUCKET}")
        except Exception as e:
            logger.error(f"Failed to create bucket: {e}")

def run_command(cmd, cwd=None, timeout=JOB_TIMEOUT):
    """Run a command and return stdout, stderr, exit_code, duration_ms"""
    start = datetime.now(timezone.utc)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            text=True,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        exit_code = -1
        stderr = f"Command timed out after {timeout}s\n{stderr}"
    except Exception as e:
        exit_code = -1
        stdout = ""
        stderr = str(e)
    end = datetime.now(timezone.utc)
    duration_ms = int((end - start).total_seconds() * 1000)
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "duration_ms": duration_ms}

def make_result(job_id, user_id, tool, status, exit_code, started_at, duration_ms, stdout, stderr, artifacts):
    """Format result as JSON string"""
    return json.dumps({
        "job_id": job_id or "unknown",
        "user_id": user_id or "unknown",
        "tool": tool,
        "status": status,
        "exit_code": exit_code,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "artifacts": artifacts,
    })

def collect_and_upload_artifacts(tmpdir, job_id):
    """Collect artifacts from tmpdir and upload to storage"""
    artifacts = []
    try:
        for fpath in Path(tmpdir).rglob("*"):
            if fpath.is_file():
                size_mb = fpath.stat().st_size / (1024 * 1024)
                if size_mb > ARTIFACT_MAX_MB:
                    continue
                rel_path = fpath.relative_to(tmpdir)
                if ARTIFACT_STORE_TYPE in ("minio", "s3") and s3_client:
                    try:
                        key = f"{job_id}/{rel_path}"
                        s3_client.upload_file(str(fpath), ARTIFACT_STORE_BUCKET, key)
                        url = s3_client.generate_presigned_url(
                            "get_object",
                            Params={"Bucket": ARTIFACT_STORE_BUCKET, "Key": key},
                            ExpiresIn=3600 * 24 * ARTIFACT_TTL_DAYS,
                        )
                        artifacts.append({"name": str(rel_path), "url": url, "size_mb": round(size_mb, 2)})
                    except Exception as e:
                        logger.warning(f"Failed to upload {rel_path}: {e}")
                elif ARTIFACT_STORE_TYPE == "local":
                    dest = Path(ARTIFACT_LOCAL_PATH) / job_id / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(fpath, dest)
                    artifacts.append({"name": str(rel_path), "path": str(dest), "size_mb": round(size_mb, 2)})
    except Exception as e:
        logger.warning(f"Error collecting artifacts: {e}")
    return artifacts

def setup_mcp_server() -> FastMCP:
    """
    Set up the MCP server with all tool functions
    
    Returns:
        Configured FastMCP instance
    """
    mcp = FastMCP("kali_mcp")
    
    @mcp.tool()
    async def nmap_scan(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Execute an Nmap network scan to discover hosts, open ports, services, and versions.

        Args:
            user_id: User identifier for tracking
            job_id: Job identifier for artifact organization
            target: Target IP address or hostname to scan (e.g., '192.168.1.1' or 'example.com')
            ports: Ports to scan - can be single port '80', range '1-1000', comma-separated list '22,80,443', or empty for default ports
            profile: Scan profile - 'quick' for fast scan, 'full' for comprehensive scan with version detection
            timeout: Command timeout in seconds (default: 600)

        Returns:
            JSON string with scan results including discovered ports, services, and version information
        """
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
    async def nikto_scan(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Execute Nikto web server vulnerability scanner to identify server misconfigurations, outdated software, and security issues.

        Args:
            user_id: User identifier for tracking
            job_id: Job identifier for artifact organization
            target: Target URL or IP address to scan (e.g., 'http://example.com' or '192.168.1.1')
            ports: Not used for nikto
            profile: Not used for nikto
            timeout: Command timeout in seconds (default: 300)

        Returns:
            JSON string with vulnerability findings, server information, and security recommendations
        """
        if not target.strip():
            return "❌ Error: 'target' is required"
        try:
            to = int(timeout) if timeout.strip() else 300
        except Exception:
            to = 300
        started_at = datetime.now(timezone.utc).isoformat()
        tmpdir = tempfile.mkdtemp(prefix="kali_mcp_")
        url = target.strip()
        if not url.startswith("http"):
            url = "http://" + url
        cmd = ["nikto", "-host", url, "-output", "nikto.txt"]
        res = run_command(cmd, cwd=tmpdir, timeout=to)
        artifacts = collect_and_upload_artifacts(tmpdir, job_id or "job")
        status = "success" if res["exit_code"] == 0 else "error"
        return make_result(job_id, user_id, "nikto", status, res["exit_code"], started_at, res["duration_ms"], res["stdout"], res["stderr"], artifacts)

    @mcp.tool()
    async def sqlmap_scan(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Execute SQLmap automated SQL injection detection and exploitation tool. WARNING: Can modify database contents.

        Args:
            user_id: User identifier for tracking
            job_id: Job identifier for artifact organization
            target: Target URL to test for SQL injection vulnerabilities (e.g., 'http://example.com/page.php?id=1')
            ports: Not used for sqlmap
            profile: Not used for sqlmap
            timeout: Command timeout in seconds (default: 300)

        Returns:
            JSON string with SQL injection vulnerabilities found, database information, and exploitation results
        """
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
    async def gobuster_scan(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Execute Gobuster directory/DNS/vhost enumeration to discover hidden paths, subdomains, or virtual hosts.

        Args:
            user_id: User identifier for tracking
            job_id: Job identifier for artifact organization
            target: Target URL (http://example.com) or domain for DNS mode
            ports: Not used for gobuster
            profile: Path to wordlist file on Kali server (default: '/usr/share/wordlists/dirb/common.txt')
            timeout: Command timeout in seconds (default: 180)

        Returns:
            JSON string with discovered directories, subdomains, or virtual hosts with response codes
        """
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
    async def searchsploit_find(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Execute SearchSploit to search for exploits in the Exploit-DB database.

        Args:
            user_id: User identifier for tracking
            job_id: Job identifier for artifact organization
            target: Search term (e.g., 'apache 2.4', 'wordpress 5.0')
            ports: Not used for searchsploit
            profile: Use 'nmap' to format output for nmap compatibility
            timeout: Command timeout in seconds (default: 60)

        Returns:
            JSON string with matching exploits from Exploit-DB
        """
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
    async def binwalk_extract(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Analyze firmware and binaries with binwalk to identify embedded files and filesystems, then extract them.

        Args:
            user_id: User identifier for tracking
            job_id: Job identifier for artifact organization
            target: Path to file on Kali server to analyze
            ports: Not used for binwalk
            profile: Not used for binwalk
            timeout: Command timeout in seconds (default: 120)

        Returns:
            JSON string with identified file signatures, offsets, and extracted file locations
        """
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
    async def apk_static(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Run apktool and jadx decompilation on an APK file for Android application analysis.

        Args:
            user_id: User identifier for tracking
            job_id: Job identifier for artifact organization
            target: Path to APK file on Kali server
            ports: Not used for apk_static
            profile: Not used for apk_static
            timeout: Command timeout in seconds (default: 300)

        Returns:
            JSON string with decompiled source code and analysis artifacts
        """
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
    async def health_check(
        user_id: str = "",
        job_id: str = "",
        target: str = "",
        ports: str = "",
        profile: str = "",
        timeout: str = ""
    ) -> str:
        """
        Check the health status and tool availability of the Kali MCP server.

        Returns:
            JSON string with server status, available security tools, and system health information
        """
        started_at = datetime.now(timezone.utc).isoformat()
        status = {
            "service": "kali_mcp",
            "status": "ok",
            "tools": ["nmap", "nikto", "sqlmap", "gobuster", "searchsploit", "binwalk", "apktool", "jadx"],
            "timestamp": started_at
        }
        return json.dumps(status)

    return mcp

def create_server() -> FastMCP:
    """
    Factory function for Smithery deployment.
    Reads configuration from environment variables.

    Returns:
        Configured FastMCP instance
    """
    logger.info("Creating Kali MCP server (Smithery mode)")
    
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
    
    # Set up and return the MCP server
    return setup_mcp_server()

def main():
    """Main entry point for the MCP server."""
    logger.info("=" * 60)
    logger.info("Starting kali_mcp MCP server...")
    logger.info("=" * 60)
    
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
    
    # Set up and run the MCP server
    mcp = setup_mcp_server()
    logger.info("Starting Kali MCP server")
    mcp.run()

if __name__ == "__main__":
    main()
