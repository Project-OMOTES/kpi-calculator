# Secure Database Connectivity Setup

This document explains how to securely configure database connectivity for the KPI Calculator, particularly for InfluxDB time series data referenced in ESDL files.

## Overview

The KPI Calculator now uses a **secure credential management system** that eliminates hard-coded credentials. Database credentials are loaded from:

1. **Environment variables** (primary, recommended for production)
2. **Configuration files** (secondary, useful for development)
3. **No hard-coded fallbacks** (secure by default)

## Security Improvements ✅

- ✅ **No credentials in source code** - eliminates security vulnerabilities
- ✅ **Environment variable support** - production-ready credential management
- ✅ **Secure config file support** - with permission validation
- ✅ **Fail-secure design** - raises clear errors when credentials are missing
- ✅ **Comprehensive error messages** - guides users to correct setup

## Environment Variable Configuration (Recommended)

### Variable Format

For each database host:port combination, set these environment variables:

```bash
KPI_DB_{HOST}_{PORT}_{FIELD}
```

Where:
- `{HOST}` = Database host with dots/hyphens replaced by underscores, uppercase
- `{PORT}` = Database port number
- `{FIELD}` = One of: `USERNAME`, `PASSWORD`, `DATABASE`, `SSL`, `VERIFY_SSL`

### Simulator-Worker Compatibility

For integration with OMOTES simulator-worker, the KPI Calculator also supports fallback to:

```bash
INFLUXDB_USERNAME
INFLUXDB_PASSWORD
INFLUXDB_DATABASE
```

These are used when `KPI_DB_*` variables are not set. The database name from the ESDL InfluxDBProfile takes precedence.

### Examples

**For wu-profiles.esdl-beta.hesi.energy:443:**
```bash
export KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443_USERNAME="your_username"
export KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443_PASSWORD="your_password"
export KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443_DATABASE="energy_profiles"
export KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443_SSL="true"
export KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443_VERIFY_SSL="true"
```

**For omotes-poc-test.hesi.energy:8086:**
```bash
export KPI_DB_OMOTES_POC_TEST_HESI_ENERGY_8086_USERNAME="your_username"
export KPI_DB_OMOTES_POC_TEST_HESI_ENERGY_8086_PASSWORD="your_password"
export KPI_DB_OMOTES_POC_TEST_HESI_ENERGY_8086_DATABASE="test_database"
export KPI_DB_OMOTES_POC_TEST_HESI_ENERGY_8086_SSL="false"
```

### Required vs Optional Variables

**Required:**
- `USERNAME` - Database username
- `PASSWORD` - Database password

**Optional (with defaults):**
- `DATABASE` - Database name (default: "energy_profiles")
- `SSL` - Use SSL connection (default: "false")
- `VERIFY_SSL` - Verify SSL certificates (default: "false")

**Fallback (simulator-worker compatibility):**
- `INFLUXDB_USERNAME` - Used if `KPI_DB_*_USERNAME` not set
- `INFLUXDB_PASSWORD` - Used if `KPI_DB_*_PASSWORD` not set
- `INFLUXDB_DATABASE` - Used if `KPI_DB_*_DATABASE` not set

## Configuration File Setup (Alternative)

### File Location

Create a secure configuration file at:
- **Linux/Mac:** `~/.kpi-calculator/credentials.json`
- **Windows:** `C:\Users\{username}\.kpi-calculator\credentials.json`

### File Format

```json
{
  "databases": {
    "wu-profiles.esdl-beta.hesi.energy:443": {
      "host": "wu-profiles.esdl-beta.hesi.energy",
      "port": 443,
      "username": "your_username",
      "password": "your_password",
      "database": "energy_profiles",
      "ssl": true,
      "verify_ssl": true
    },
    "omotes-poc-test.hesi.energy:8086": {
      "host": "omotes-poc-test.hesi.energy",
      "port": 8086,
      "username": "your_username",
      "password": "your_password",
      "database": "test_database",
      "ssl": false,
      "verify_ssl": false
    }
  }
}
```

### File Permissions (Security)

**Important:** The configuration file must have secure permissions:

```bash
# Linux/Mac - Set file readable only by owner
chmod 600 ~/.kpi-calculator/credentials.json

# Windows - Restrict file access through Properties > Security
```

The system will raise a `SecurityError` if file permissions are too permissive.

## Usage in Code

### Basic Usage

```python
from kpicalculator import KpiManager
from kpicalculator.adapters import EsdlAdapter

# Create adapter - credentials loaded automatically
adapter = EsdlAdapter()

# Load ESDL file with database profiles
energy_system = adapter.load_data(
    source="path/to/model.esdl",
    use_database_profiles=True  # Default
)

# Use with KPI Manager
kpi_manager = KpiManager()
kpi_manager.add_energy_system(energy_system)
results = kpi_manager.calculate_all_kpis()
```

### Custom Credential Manager

```python
from kpicalculator.security import SecureCredentialManager
from kpicalculator.adapters import EsdlAdapter

# Use only environment variables
env_manager = SecureCredentialManager()
adapter = EsdlAdapter(credential_manager=env_manager)
```

### Testing with Mock Credentials

```python
import os
from unittest.mock import patch
from kpicalculator.adapters import EsdlAdapter

# Mock credentials for testing
with patch.dict(os.environ, {
    'KPI_DB_TEST_EXAMPLE_COM_8086_USERNAME': 'test_user',
    'KPI_DB_TEST_EXAMPLE_COM_8086_PASSWORD': 'test_pass'
}):
    adapter = EsdlAdapter()
    # Test with mock credentials...
```

## Error Handling

### Common Error Messages

**No Credentials Found:**
```
CredentialError: No credentials found for wu-profiles.esdl-beta.hesi.energy:443. 
Set environment variables or configure credentials file.
Context: env_prefix=KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443
```

**Insecure File Permissions:**
```
SecurityError: Credentials file has insecure permissions: ~/.kpi-calculator/credentials.json. 
File should only be readable by owner (chmod 600).
```

**Invalid Configuration:**
```
ConfigurationError: Invalid JSON in credentials file: ~/.kpi-calculator/credentials.json
```

### Resolution Steps

1. **Check environment variables** are set correctly
2. **Verify credential file format** and permissions
3. **Test database connectivity** independently
4. **Check ESDL file** InfluxDBProfile elements

## Migration from Old System

If you're migrating from a system with hard-coded credentials:

1. **Identify all database hosts** in your ESDL files
2. **Set environment variables** for each host:port combination
3. **Test connectivity** with a simple ESDL file
4. **Remove any hard-coded credentials** from your code
5. **Update CI/CD pipelines** to set environment variables

## Production Deployment

### Environment Variables (Recommended)

```bash
# Production environment setup
export KPI_DB_PROD_INFLUX_COMPANY_COM_443_USERNAME="production_user"
export KPI_DB_PROD_INFLUX_COMPANY_COM_443_PASSWORD="$(cat /secure/path/to/password)"
export KPI_DB_PROD_INFLUX_COMPANY_COM_443_SSL="true"
export KPI_DB_PROD_INFLUX_COMPANY_COM_443_VERIFY_SSL="true"
```

### Docker Example

```dockerfile
# Dockerfile
FROM python:3.10
# Install KPI Calculator...

# Set at runtime via docker run -e or docker-compose
ENV KPI_DB_PROD_INFLUX_COMPANY_COM_443_USERNAME=""
ENV KPI_DB_PROD_INFLUX_COMPANY_COM_443_PASSWORD=""
```

### Kubernetes Example

```yaml
# kubernetes-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: kpi-calculator-db-credentials
type: Opaque
stringData:
  KPI_DB_PROD_INFLUX_COMPANY_COM_443_USERNAME: "production_user"
  KPI_DB_PROD_INFLUX_COMPANY_COM_443_PASSWORD: "secure_password"
---
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: kpi-calculator
        envFrom:
        - secretRef:
            name: kpi-calculator-db-credentials
```

## Troubleshooting

### Debug Mode

Enable debug logging to see credential loading:

```python
import logging
logging.getLogger('kpicalculator.security').setLevel(logging.DEBUG)
logging.getLogger('kpicalculator.adapters').setLevel(logging.DEBUG)
```

### Test Connectivity

```python
from kpicalculator.security import create_default_credential_manager

manager = create_default_credential_manager()
creds = manager.get_database_credentials("your.host.com", 8086)

if creds:
    print(f"✅ Credentials found for {creds.username}")
else:
    print("❌ No credentials found - check environment variables")
```

## Security Best Practices

1. **Never commit credentials** to version control
2. **Use environment variables** in production
3. **Restrict file permissions** for config files (600)
4. **Rotate credentials** regularly
5. **Use separate credentials** for different environments
6. **Monitor access logs** in your databases
7. **Use SSL/TLS connections** when possible

## Support

If you encounter issues:

1. Check the error message and context
2. Verify environment variable names (case-sensitive)
3. Test with a minimal ESDL file
4. Enable debug logging
5. Check database server logs

For additional help, refer to the project's issue tracker or documentation.