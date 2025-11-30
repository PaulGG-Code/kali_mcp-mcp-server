# Kali Linux MCP Server

<div align="center">

**AI-Powered Kali Linux Penetration Testing Toolkit via Model Context Protocol**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-1.13+-green.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

</div>

## Overview

Kali MCP Server is a Model Context Protocol (MCP) server that exposes Kali Linux penetration testing tools to AI agents. It enables AI assistants to perform security assessments, penetration testing, and CTF challenges through a standardized interface.

## Features

### 🔧 Core Tools (60+ Security Tools)

#### Network Scanning & Reconnaissance
- **Nmap** - Network port scanning and service detection
- **Masscan** - Ultra-fast port scanner for large IP ranges
- **Nikto** - Web server vulnerability scanner
- **Gobuster** - Directory/DNS/vhost enumeration
- **Dirb** - Web content scanner
- **Enum4linux** - Windows/Samba enumeration

#### Web Application Security
- **SQLMap** - Automated SQL injection detection
- **WPScan** - WordPress security scanner
- **Ffuf** - Fast web fuzzer for directories, vhosts, and parameters

#### Password Attacks
- **Hydra** - Online password cracking
- **John the Ripper** - Offline password hash cracking
- **Hashcat** - GPU-accelerated hash cracking

#### Exploitation
- **Metasploit Framework** - Exploitation framework integration
- **Searchsploit** - Exploit-DB search tool

#### Binary Analysis & Pwnable
- **Checksec** - Binary security protections analysis
- **ROPgadget** - ROP gadget finder
- **Radare2** - Binary analysis framework
- **Objdump** - Binary disassembler
- **Strace** - System call tracer
- **Ltrace** - Library call tracer
- **Strings** - String extractor
- **Pwntools** - Exploit development framework

#### Mobile Security
- **Apktool** - Android APK decompiler (Smali)
- **JADX** - Android APK to Java decompiler

#### Forensics
- **Volatility3** - Memory dump analysis
- **Binwalk** - Firmware and binary analysis
- **Steghide** - Steganography extraction
- **Foremost** - File carver
- **Exiftool** - Metadata extraction
- **Tesseract OCR** - Optical character recognition
- **Sleuthkit** - Disk forensics
- **YARA** - Malware detection

#### Cryptography
- **RSA attacks** - RSA attack tools (RsaCtfTool)
- **Hashcat** - Hash cracking
- **FactorDB** - Integer factorization
- **OpenSSL** - Cryptographic operations
- **SageMath** - Mathematical computations

#### Cloud Security
- **AWS CLI** - AWS resource enumeration
- **Pacu** - AWS exploitation framework
- **S3Scanner** - S3 bucket scanning
- **ScoutSuite** - Cloud security auditing

#### Web3/Blockchain Security
- **Slither** - Solidity static analysis
- **Mythril** - Smart contract symbolic execution
- **Solc** - Solidity compiler
- **Web3.py** - Blockchain interaction

### 🎯 Key Capabilities
- **60+ Security Tools**: Comprehensive toolkit covering all major security testing domains
- **Session Management**: Create and manage analysis sessions with workspace isolation
- **File Management**: Upload binaries, list files, manage artifacts
- **Interactive Shells**: Bidirectional communication with running processes
- **Automated Analysis**: AI-powered vulnerability detection and automated workflows
- **Resource Access**: Wordlists, safety guides, tool documentation, and workflow prompts
- **Workflow Prompts**: Pre-built prompts for common security testing scenarios
- **Mobile Security**: Android APK analysis with Apktool and JADX
- **Exploit Research**: Search Exploit-DB for known exploits
- **Fast Scanning**: Masscan and Ffuf for high-speed reconnaissance

## Architecture

The Kali MCP Server uses a two-tier architecture that separates tool execution from the MCP protocol interface:

```
┌─────────────────────────────────────────────────────────────────┐
│                         AI Agent / Client                        │
│                    (Claude, ChatGPT, etc.)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ MCP Protocol (HTTP/SSE)
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                    MCP Server Layer                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  src/kali_mcp_server/mcp_server.py                       │  │
│  │  • FastMCP Framework                                      │  │
│  │  • Tool Registration (60+ tools)                          │  │
│  │  • Resource Providers                                     │  │
│  │  • Workflow Prompts                                       │  │
│  │  • Session Management                                     │  │
│  └────────────────────┬─────────────────────────────────────┘  │
└────────────────────────┼────────────────────────────────────────┘
                         │
                         │ HTTP REST API
                         │
┌────────────────────────▼────────────────────────────────────────┐
│              Kali Tools API Server Layer                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  kali_server.py (Flask)                                   │  │
│  │  • Command Execution                                      │  │
│  │  • Session Management                                     │  │
│  │  • File Management                                        │  │
│  │  • Interactive Shells                                     │  │
│  └────────────────────┬─────────────────────────────────────┘  │
└────────────────────────┼────────────────────────────────────────┘
                         │
                         │ Subprocess Execution
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  Kali Linux Tools Layer                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  • Network Tools: nmap, masscan, ffuf, gobuster          │  │
│  │  • Web Tools: sqlmap, wpscan, nikto                      │  │
│  │  • Password Tools: hydra, john, hashcat                  │  │
│  │  • Binary Tools: gdb, radare2, checksec, ropgadget       │  │
│  │  • Forensics: volatility, binwalk, steghide              │  │
│  │  • Mobile: apktool, jadx                                 │  │
│  │  • Crypto: openssl, rsactftool, sage                     │  │
│  │  • Cloud: aws-cli, pacu, s3scanner                       │  │
│  │  • Web3: slither, mythril, solc                          │  │
│  │  • And 40+ more tools...                                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Details

1. **MCP Server** (`src/kali_mcp_server/mcp_server.py`)
   - FastMCP-based server implementing the Model Context Protocol
   - Exposes 60+ security tools as MCP tools
   - Provides resources (wordlists, guides, tool info)
   - Offers workflow prompts for common security testing scenarios
   - Manages communication with the API server

2. **Kali Tools API Server** (`kali_server.py`)
   - Flask-based REST API server
   - Executes Kali Linux tools via subprocess
   - Manages analysis sessions and workspaces
   - Handles file uploads/downloads
   - Provides interactive shell capabilities
   - Runs on port 5000 by default

3. **Kali Linux Tools**
   - All tools run in isolated Docker container
   - Tools execute with proper permissions
   - Output captured and returned via API
   - Session-based workspace isolation

## Installation

### Prerequisites
- Python 3.12+
- Kali Linux tools installed
- Docker (optional, for containerized deployment)

### Local Setup

1. Clone the repository:
```bash
git clone https://github.com/PaulGG-Code/kali_mcp-mcp-server
cd kali_mcp-mcp-server
git checkout -b smithery
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

## Tools Reference

### Network Reconnaissance
- `nmap_scan`: Network port scanning and service detection
- `masscan_scan`: Ultra-fast port scanner for large IP ranges
- `gobuster_scan`: Directory/DNS/vhost enumeration
- `ffuf_scan`: Fast web fuzzer for directories, vhosts, and parameters
- `nikto_scan`: Web server vulnerability scanning
- `dirb_scan`: Web content scanner
- `enum4linux_scan`: Windows/Samba enumeration

### Web Application Testing
- `sqlmap_scan`: Automated SQL injection detection
- `wpscan_analyze`: WordPress security scanning
- `ffuf_scan`: Fast web fuzzer (directories, vhosts, parameters)

### Password Attacks
- `hydra_attack`: Online password cracking
- `john_crack`: Offline password hash cracking
- `hashcat_crack`: GPU-accelerated hash cracking

### Exploitation
- `metasploit_run`: Execute Metasploit Framework modules
- `searchsploit_find`: Search Exploit-DB for exploits

### Binary Analysis & Pwnable
- `checksec_binary`: Analyze binary security protections
- `find_rop_gadgets`: Search for ROP gadgets
- `analyze_with_radare2`: Binary analysis with Radare2
- `disassemble_binary`: Disassemble binaries with Objdump
- `trace_syscalls`: Trace system calls with Strace
- `trace_library_calls`: Trace library calls with Ltrace
- `extract_strings`: Extract printable strings from binaries
- `run_pwntools_exploit`: Execute exploits using Pwntools
- `auto_detect_vulnerabilities`: AI-powered vulnerability detection

### Mobile Security
- `apktool_decompile`: Decompile/rebuild Android APK files (Smali)
- `jadx_decompile`: Decompile Android APK to Java source code

### Forensics
- `volatility_analyze`: Memory dump analysis
- `binwalk_analyze`: Firmware and binary analysis
- `steghide_extract`: Steganography extraction
- `foremost_carve`: File carving and recovery
- `exiftool_analyze`: Metadata extraction
- `tesseract_ocr`: Optical character recognition
- `auto_memory_analysis`: Automated memory forensics workflow
- `auto_disk_analysis`: Automated disk forensics workflow
- `auto_malware_hunt`: Automated malware detection

### Cryptography
- `rsa_attack`: RSA attack tools (RsaCtfTool)
- `hashcat_crack`: Hash cracking
- `factordb_query`: Integer factorization
- `openssl_operation`: OpenSSL cryptographic operations
- `sage_execute`: SageMath script execution

### Cloud Security
- `aws_enumerate`: AWS resource enumeration
- `s3_bucket_scan`: S3 bucket scanning
- `cloud_metadata_query`: Cloud metadata service queries
- `pacu_aws_exploit`: AWS exploitation framework

### Web3/Blockchain Security
- `slither_analyze`: Solidity static analysis
- `mythril_analyze`: Smart contract symbolic execution
- `solidity_compile`: Solidity compilation
- `web3_interact`: Blockchain interaction

### Session & File Management
- `create_analysis_session`: Create isolated analysis workspace
- `save_analysis_result`: Save analysis context and results
- `load_analysis_results`: Load previous analysis results
- `upload_binary`: Upload files for analysis
- `list_session_files`: List files in session workspace
- `start_interactive_shell`: Start interactive shell session
- `send_to_shell`: Send commands to interactive shell
- `read_shell_output`: Read output from interactive shell
- `close_shell`: Close interactive shell session

### Resources & Prompts
- **Resources**: Access wordlists, tool guides, and safety guidelines
- **Prompts**: Pre-built workflows for common security testing scenarios:
  - `network_reconnaissance`: Comprehensive network scanning workflow
  - `web_application_testing`: Web app security assessment workflow
  - `password_attack_workflow`: Credential testing workflow
  - `pwnable_challenge_workflow`: Binary exploitation workflow
  - `reversing_challenge_workflow`: Reverse engineering workflow
  - `android_app_analysis_workflow`: Android app security analysis
  - `crypto_challenge_workflow`: Cryptography challenge workflow
  - `forensics_challenge_workflow`: Digital forensics workflow
  - `cloud_security_workflow`: Cloud security assessment workflow
  - `web3_challenge_workflow`: Smart contract security workflow

## Safety and Legal Notice

⚠️ **IMPORTANT**: This tool is for authorized security testing only.

- Always obtain written authorization before testing
- Only test systems you own or have explicit permission to test
- Follow responsible disclosure practices
- Never use these tools maliciously

See the `kali://guides/safe-testing` resource for detailed safety guidelines.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Inspired by the Model Context Protocol specification
- Built with FastMCP framework
- Uses Kali Linux penetration testing tools

## Support

For issues, questions, or contributions, please open an issue on the repository.
