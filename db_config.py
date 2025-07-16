import mysql.connector
import json
import os
from pathlib import Path
import subprocess
import sys
from cryptography.fernet import Fernet
from base64 import b64encode, b64decode

def get_encryption_key():
    key_path = Path(os.getenv('APPDATA')) / 'FP2PivotApp' / '.key'
    if not key_path.exists():
        key = Fernet.generate_key()
        key_path.write_bytes(key)
    return key_path.read_bytes()

def get_config_path():
    app_data = os.getenv('APPDATA')
    config_dir = Path(app_data) / 'FP2PivotApp'
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / 'db_config.json'

def save_config(config):
    config_path = get_config_path()
    # Convert config to JSON string
    json_data = json.dumps(config)
    # Encrypt the data
    fernet = Fernet(get_encryption_key())
    encrypted_data = fernet.encrypt(json_data.encode())
    # Save encrypted data
    with open(config_path, 'wb') as f:
        f.write(encrypted_data)

def load_config():
    config_path = get_config_path()
    if not config_path.exists():
        return None
    try:
        # Read encrypted data
        with open(config_path, 'rb') as f:
            encrypted_data = f.read()
        # Decrypt the data
        fernet = Fernet(get_encryption_key())
        decrypted_data = fernet.decrypt(encrypted_data)
        # Parse JSON
        return json.loads(decrypted_data)
    except Exception as e:
        print(f"Error loading config: {str(e)}")
        return None

def is_db_configured():
    return load_config() is not None

def test_connection(config):
    try:
        # Test local connection
        try:
            local_conn = mysql.connector.connect(
                host=config['local_host'],
                port=config['local_port'],
                database=config['local_database'],
                user=config['local_user'],
                password=config['local_password']
            )
            local_conn.close()
        except mysql.connector.Error as e:
            if e.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                return False, f"Local Database (A): Access denied - Invalid username or password"
            elif e.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
                return False, f"Local Database (A): Database '{config['local_database']}' does not exist"
            elif e.errno == mysql.connector.errorcode.CR_CONN_HOST_ERROR:
                return False, f"Local Database (A): Cannot connect to host '{config['local_host']}:{config['local_port']}"
            else:
                return False, f"Local Database (A): {str(e)}"

        # Test OWL connection
        try:
            owl_conn = mysql.connector.connect(
                host=config['owl_host'],
                port=config['owl_port'],
                database=config['owl_database'],
                user=config['owl_user'],
                password=config['owl_password']
            )
            owl_conn.close()
        except mysql.connector.Error as e:
            if e.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                return False, f"OWL Database (B): Access denied - Invalid username or password"
            elif e.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
                return False, f"OWL Database (B): Database '{config['owl_database']}' does not exist"
            elif e.errno == mysql.connector.errorcode.CR_CONN_HOST_ERROR:
                return False, f"OWL Database (B): Cannot connect to host '{config['owl_host']}:{config['owl_port']}"
            else:
                return False, f"OWL Database (B): {str(e)}"
        
        return True, None
    except Exception as e:
        return False, f"General error: {str(e)}"

def get_connection():
    config = load_config()
    if not config:
        raise Exception("Database not configured")
    
    try:
        return mysql.connector.connect(
            host=config['local_host'],
            port=config['local_port'],
            database=config['local_database'],
            user=config['local_user'],
            password=config['local_password']
        )
    except mysql.connector.Error as e:
        if e.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
            raise Exception(f"Local Database (A): Access denied - Invalid username or password")
        elif e.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
            raise Exception(f"Local Database (A): Database '{config['local_database']}' does not exist")
        elif e.errno == mysql.connector.errorcode.CR_CONN_HOST_ERROR:
            raise Exception(f"Local Database (A): Cannot connect to host '{config['local_host']}:{config['local_port']}'")
        else:
            raise Exception(f"Local Database (A): {str(e)}")
    except Exception as e:
        raise Exception(f"Local Database (A): Connection error - {str(e)}")

def get_owl_connection():
    config = load_config()
    if not config:
        raise Exception("Database not configured")
    
    try:
        return mysql.connector.connect(
            host=config['owl_host'],
            port=config['owl_port'],
            database=config['owl_database'],
            user=config['owl_user'],
            password=config['owl_password']
        )
    except mysql.connector.Error as e:
        if e.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
            raise Exception(f"OWL Database (B): Access denied - Invalid username or password")
        elif e.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
            raise Exception(f"OWL Database (B): Database '{config['owl_database']}' does not exist")
        elif e.errno == mysql.connector.errorcode.CR_CONN_HOST_ERROR:
            raise Exception(f"OWL Database (B): Cannot connect to host '{config['owl_host']}:{config['owl_port']}'")
        else:
            raise Exception(f"OWL Database (B): {str(e)}")
    except Exception as e:
        raise Exception(f"OWL Database (B): Connection error - {str(e)}")


def check_and_install_requirements():
    required_packages = {
        'cryptography': 'cryptography',
        'mysql-connector-python': 'mysql.connector',
        'pandas': 'pandas',
        'xlsxwriter': 'xlsxwriter',
        'flaskwebgui': 'flaskwebgui',
        'Flask': 'flask'
    }
    
    missing_packages = []
    
    for package, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("Missing required packages. Installing...")
        try:
            for package in missing_packages:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print("All required packages installed successfully!")
            # Reload the modules after installation
            for package, import_name in required_packages.items():
                if package in missing_packages:
                    __import__(import_name)
        except Exception as e:
            print(f"Error installing packages: {str(e)}")
            sys.exit(1)

# Add this at the beginning of the file
check_and_install_requirements()