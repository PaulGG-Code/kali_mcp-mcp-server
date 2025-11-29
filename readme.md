# 🛡️ Kali MCP Server

<div align="center">

**AI-Powered Kali Linux Penetration Testing Toolkit via Model Context Protocol**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-1.13+-green.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

</div>

## Overview

Kali MCP Server is a Model Context Protocol (MCP) server that exposes Kali Linux penetration testing tools to AI agents. It enables AI assistants to perform security assessments, penetration testing, and CTF challenges through a standardized interface.

## Features

### 🔧 Core Tools
- **Network Scanning**: Nmap, Nikto, Gobuster, Dirb
- **Web Security**: SQLMap, WPScan, Nikto
- **Password Attacks**: Hydra, John the Ripper, Hashcat
- **Exploitation**: Metasploit Framework integration
- **Binary Analysis**: Checksec, ROPgadget, Radare2, Objdump, Strace, Ltrace
- **Forensics**: Volatility, Binwalk, Steghide, Foremost, Exiftool, Tesseract OCR
- **Cryptography**: RSA attacks, Hashcat, FactorDB, OpenSSL, SageMath
- **Cloud Security**: AWS enumeration, S3 scanning, Cloud metadata queries
- **Web3 Security**: Slither, Mythril, Solidity compilation, Web3 interactions

### 🎯 Key Capabilities
- **Session Management**: Create and manage analysis sessions with workspace isolation
- **File Management**: Upload binaries, list files, manage artifacts
- **Interactive Shells**: Bidirectional communication with running processes
- **Automated Analysis**: AI-powered vulnerability detection and automated workflows
- **Resource Access**: Wordlists, safety guides, and workflow prompts

## Architecture

The server consists of two components:

1. **Kali Tools API Server** (`kali_server.py`): Flask-based REST API that executes Kali Linux tools
2. **MCP Server** (`src/kali_mcp_server/mcp_server.py`): FastMCP server that exposes tools via MCP protocol

## Installation

### Prerequisites
- Python 3.12+
- Kali Linux tools installed
- Docker (optional, for containerized deployment)

### Local Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd kali_mcp-mcp-server
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Start the Kali Tools API Server:
```bash
python kali_server.py
```

4. Configure the MCP server to connect to the API server (default: `http://localhost:5000`)

## Usage

### Running the MCP Server

The MCP server can be run in two modes:

#### Standalone Mode
```bash
python -m src.kali_mcp_server.mcp_server --server http://localhost:5000
```

#### Smithery Deployment
The server is configured for deployment on Smithery using `runtime: "python"`. Smithery will automatically call the `create_server()` function.

### Environment Variables

- `KALI_SERVER_URL`: URL of the Kali Tools API Server (default: `http://localhost:5000`)
- `KALI_REQUEST_TIMEOUT`: Request timeout in seconds (default: `300`)
- `API_PORT`: Port for the Kali Tools API Server (default: `5000`)
- `DEBUG_MODE`: Enable debug logging (`0` or `1`, default: `0`)

## Safety and Legal Notice

⚠️ **IMPORTANT**: This tool is for authorized security testing only.

- Always obtain written authorization before testing
- Only test systems you own or have explicit permission to test
- Follow responsible disclosure practices
- Never use these tools maliciously

## License

This project is licensed under the MIT License.

## Acknowledgments

- Built with FastMCP framework
- Uses Kali Linux penetration testing tools
